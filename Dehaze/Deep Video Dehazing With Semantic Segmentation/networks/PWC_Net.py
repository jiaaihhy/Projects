import torch

import math
import numpy
import os
import PIL
import PIL.Image
import sys

try:
	from networks.correlation import correlation # the custom cost volume layer
except:
	sys.path.insert(0, './correlation'); import correlation # you should consider upgrading python


Backward_tensorGrid = {}
Backward_tensorPartial = {}

def Backward(tensorInput, tensorFlow):
	if str(tensorFlow.size()) not in Backward_tensorGrid:
		tensorHorizontal = torch.linspace(-1.0, 1.0, tensorFlow.size(3)).view(1, 1, 1, tensorFlow.size(3)).expand(tensorFlow.size(0), -1, tensorFlow.size(2), -1)
		tensorVertical = torch.linspace(-1.0, 1.0, tensorFlow.size(2)).view(1, 1, tensorFlow.size(2), 1).expand(tensorFlow.size(0), -1, -1, tensorFlow.size(3))

		Backward_tensorGrid[str(tensorFlow.size())] = torch.cat([ tensorHorizontal, tensorVertical ], 1).cuda()
	# end

	if str(tensorFlow.size()) not in Backward_tensorPartial:
		Backward_tensorPartial[str(tensorFlow.size())] = tensorFlow.new_ones([ tensorFlow.size(0), 1, tensorFlow.size(2), tensorFlow.size(3) ])
	# end

	tensorFlow = torch.cat([ tensorFlow[:, 0:1, :, :] / ((tensorInput.size(3) - 1.0) / 2.0), tensorFlow[:, 1:2, :, :] / ((tensorInput.size(2) - 1.0) / 2.0) ], 1)
	tensorInput = torch.cat([ tensorInput, Backward_tensorPartial[str(tensorFlow.size())] ], 1)

	tensorOutput = torch.nn.functional.grid_sample(input=tensorInput, grid=(Backward_tensorGrid[str(tensorFlow.size())] + tensorFlow).permute(0, 2, 3, 1), mode='bilinear', padding_mode='zeros')

	tensorMask = tensorOutput[:, -1:, :, :]; tensorMask[tensorMask > 0.999] = 1.0; tensorMask[tensorMask < 1.0] = 0.0

	return tensorOutput[:, :-1, :, :] * tensorMask
# end

##########################################################
class Decoder(torch.nn.Module):
	def __init__(self, intLevel):
		super(Decoder, self).__init__()

		intPrevious = [81 + 64 + 2 + 2, 81 + 128 + 2 + 2, 81, None][intLevel + 1]
		intCurrent = [81 + 64 + 2 + 2, 81 + 128 + 2 + 2, 81, None][intLevel + 0]

		if intLevel < 2: self.moduleUpflow = torch.nn.ConvTranspose2d(in_channels=2, out_channels=2, kernel_size=4,
																	  stride=2, padding=1)
		if intLevel < 2: self.moduleUpfeat = torch.nn.ConvTranspose2d(
			in_channels=intPrevious + 128 + 128 + 96 + 64 + 32, out_channels=2, kernel_size=4, stride=2, padding=1)
		if intLevel < 2: self.dblBackward = [None, 20, 10, 5][intLevel + 1]

		self.moduleOne = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent, out_channels=128, kernel_size=3, stride=1, padding=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1)
		)

		self.moduleTwo = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent + 128, out_channels=128, kernel_size=3, stride=1, padding=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1)
		)

		self.moduleThr = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent + 128 + 128, out_channels=96, kernel_size=3, stride=1, padding=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1)
		)

		self.moduleFou = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent + 128 + 128 + 96, out_channels=64, kernel_size=3, stride=1,
							padding=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1)
		)

		self.moduleFiv = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent + 128 + 128 + 96 + 64, out_channels=32, kernel_size=3, stride=1,
							padding=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1)
		)

		self.moduleSix = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=intCurrent + 128 + 128 + 96 + 64 + 32, out_channels=2, kernel_size=3, stride=1,
							padding=1)
		)

	# end

	def forward(self, tensorFirst, tensorSecond, objectPrevious):
		tensorFlow = None
		tensorFeat = None

		if objectPrevious is None:
			tensorFlow = None
			tensorFeat = None

			tensorVolume = torch.nn.functional.leaky_relu(
				input=correlation.FunctionCorrelation(tensorFirst=tensorFirst, tensorSecond=tensorSecond),
				negative_slope=0.1, inplace=False)

			tensorFeat = torch.cat([tensorVolume], 1)

		elif objectPrevious is not None:
			tensorFlow = self.moduleUpflow(objectPrevious['tensorFlow'])
			tensorFeat = self.moduleUpfeat(objectPrevious['tensorFeat'])

			tensorVolume = torch.nn.functional.leaky_relu(input=correlation.FunctionCorrelation(tensorFirst=tensorFirst,
																								tensorSecond=Backward(
																									tensorInput=tensorSecond,
																									tensorFlow=tensorFlow * self.dblBackward)),
														  negative_slope=0.1, inplace=False)

			tensorFeat = torch.cat([tensorVolume, tensorFirst, tensorFlow, tensorFeat], 1)

		# end

		tensorFeat = torch.cat([self.moduleOne(tensorFeat), tensorFeat], 1)
		tensorFeat = torch.cat([self.moduleTwo(tensorFeat), tensorFeat], 1)
		tensorFeat = torch.cat([self.moduleThr(tensorFeat), tensorFeat], 1)
		tensorFeat = torch.cat([self.moduleFou(tensorFeat), tensorFeat], 1)
		tensorFeat = torch.cat([self.moduleFiv(tensorFeat), tensorFeat], 1)

		tensorFlow = self.moduleSix(tensorFeat)

		return {
			'tensorFlow': tensorFlow,
			'tensorFeat': tensorFeat
		}


# end
# end

class Refiner(torch.nn.Module):
	def __init__(self):
		super(Refiner, self).__init__()

		self.moduleMain = torch.nn.Sequential(
			torch.nn.Conv2d(in_channels=81 + 64 + 2 + 2 + 128 + 128 + 96 + 64 + 32, out_channels=128, kernel_size=3,
							stride=1, padding=1, dilation=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=128, out_channels=128, kernel_size=3, stride=1, padding=2, dilation=2),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=128, out_channels=128, kernel_size=3, stride=1, padding=4, dilation=4),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=128, out_channels=96, kernel_size=3, stride=1, padding=8, dilation=8),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=96, out_channels=64, kernel_size=3, stride=1, padding=16, dilation=16),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=64, out_channels=32, kernel_size=3, stride=1, padding=1, dilation=1),
			torch.nn.LeakyReLU(inplace=False, negative_slope=0.1),
			torch.nn.Conv2d(in_channels=32, out_channels=2, kernel_size=3, stride=1, padding=1, dilation=1)
		)

	# end

	def forward(self, tensorInput):
		return self.moduleMain(tensorInput)

class Network(torch.nn.Module):
	def __init__(self):
		super(Network, self).__init__()

		self.moduleTwo = Decoder(2)
		self.moduleOne = Decoder(1)
		self.moduleZer = Decoder(0)

		self.moduleRefiner = Refiner()

		#self.load_state_dict(torch.load('./network-' + arguments_strModel + '.pytorch'))
	# end

	def forward(self, tensorFirst, tensorSecond):
		objectEstimate = self.moduleTwo(tensorFirst[0], tensorSecond[0], None)
		flowEstimate_s4 = objectEstimate['tensorFlow']
		objectEstimate = self.moduleOne(tensorFirst[1], tensorSecond[1], objectEstimate)
		flowEstimate_s2 = objectEstimate['tensorFlow']
		objectEstimate = self.moduleZer(tensorFirst[2], tensorSecond[2], objectEstimate)
		flowEstimate_s1 = objectEstimate['tensorFlow'] + self.moduleRefiner(objectEstimate['tensorFeat'])

		return 5*flowEstimate_s4, 10*flowEstimate_s2, 20*flowEstimate_s1
	# end
# end

# moduleNetwork = Network().cuda().eval()
#
# ##########################################################
#
# def estimate(tensorFirst, tensorSecond):
# 	tensorOutput = torch.FloatTensor()
#
# 	assert(tensorFirst.size(1) == tensorSecond.size(1))
# 	assert(tensorFirst.size(2) == tensorSecond.size(2))
#
# 	intWidth = tensorFirst.size(2)
# 	intHeight = tensorFirst.size(1)
#
# 	assert(intWidth == 1024) # remember that there is no guarantee for correctness, comment this line out if you acknowledge this and want to continue
# 	assert(intHeight == 436) # remember that there is no guarantee for correctness, comment this line out if you acknowledge this and want to continue
#
# 	if True:
# 		tensorFirst = tensorFirst.cuda()
# 		tensorSecond = tensorSecond.cuda()
# 		tensorOutput = tensorOutput.cuda()
# 	# end
#
# 	if True:
# 		tensorPreprocessedFirst = tensorFirst.view(1, 3, intHeight, intWidth)
# 		tensorPreprocessedSecond = tensorSecond.view(1, 3, intHeight, intWidth)
#
# 		intPreprocessedWidth = int(math.floor(math.ceil(intWidth / 64.0) * 64.0))
# 		intPreprocessedHeight = int(math.floor(math.ceil(intHeight / 64.0) * 64.0))
#
# 		tensorPreprocessedFirst = torch.nn.functional.interpolate(input=tensorPreprocessedFirst, size=(intPreprocessedHeight, intPreprocessedWidth), mode='bilinear', align_corners=False)
# 		tensorPreprocessedSecond = torch.nn.functional.interpolate(input=tensorPreprocessedSecond, size=(intPreprocessedHeight, intPreprocessedWidth), mode='bilinear', align_corners=False)
#
# 		tensorFlow = 20.0 * torch.nn.functional.interpolate(input=moduleNetwork(tensorPreprocessedFirst, tensorPreprocessedSecond), size=(intHeight, intWidth), mode='bilinear', align_corners=False)
#
# 		tensorFlow[:, 0, :, :] *= float(intWidth) / float(intPreprocessedWidth)
# 		tensorFlow[:, 1, :, :] *= float(intHeight) / float(intPreprocessedHeight)
#
# 		tensorOutput.resize_(2, intHeight, intWidth).copy_(tensorFlow[0, :, :, :])
# 	# end
#
# 	if True:
# 		tensorFirst = tensorFirst.cpu()
# 		tensorSecond = tensorSecond.cpu()
# 		tensorOutput = tensorOutput.cpu()
# 	# end
#
# 	return tensorOutput
# # end
#
# ##########################################################
#
# if __name__ == '__main__':
# 	tensorFirst = torch.FloatTensor(numpy.array(PIL.Image.open(arguments_strFirst))[:, :, ::-1].transpose(2, 0, 1).astype(numpy.float32) * (1.0 / 255.0))
# 	tensorSecond = torch.FloatTensor(numpy.array(PIL.Image.open(arguments_strSecond))[:, :, ::-1].transpose(2, 0, 1).astype(numpy.float32) * (1.0 / 255.0))
#
# 	tensorOutput = estimate(tensorFirst, tensorSecond)
#
# 	objectOutput = open(arguments_strOut, 'wb')
#
# 	numpy.array([ 80, 73, 69, 72 ], numpy.uint8).tofile(objectOutput)
# 	numpy.array([ tensorOutput.size(2), tensorOutput.size(1) ], numpy.int32).tofile(objectOutput)
# 	numpy.array(tensorOutput.numpy().transpose(1, 2, 0), numpy.float32).tofile(objectOutput)
#
# 	objectOutput.close()