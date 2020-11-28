import os
import shutil

# folder_path = r'D:\CV_PAPER_PROJECT\DH\results\no_local_dehaze_group'
folder_path = r'E:\DataSet\test_psnr_results\gcanet_results'
folders = os.listdir(folder_path)
for folder in folders:
    folder_name = os.path.join(folder_path, folder)
    img_names = os.listdir(folder_name)
    for img_name in img_names:
        old = os.path.join(folder_name, img_name)
        new_name = img_name[1:6]+'_GCANet.JPG'
        new = os.path.join(folder_name, new_name)
        os.rename(old, new)