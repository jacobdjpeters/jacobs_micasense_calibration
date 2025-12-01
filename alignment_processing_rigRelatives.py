#! /usr/bin/env python
"""
Driver script for a flight bounded by reflectance panels pre- and post-flight.
Do this prior to running process_flight_images.py, which calibrates reflectance. 
"""

import sys
sys.path.insert(0, '/media/jacob/linux/Dropbox/cloned_repos/imageprocessing')

import matplotlib.pyplot as plt
import micasense.capture as capture
import micasense.panel as panel 
import pandas as pd
import glob
# from libtiff import TIFFimage

# import tifffile as TIFFimage
import subprocess
import argparse
import os
import datetime
import numpy as np
import exiftool
import imageio
from osgeo import gdal, gdal_array
from numpy import array
from numpy import float32
#%matplotlib inline
from pathlib import Path
plt.rcParams["figure.facecolor"] = "w"
import cv2
import time
import numpy as np
import matplotlib.pyplot as plt
import micasense.imageutils as imageutils

import micasense.imageutils as imageutils
print("imageutils loaded from:", imageutils.__file__)
print("Available functions:", [x for x in dir(imageutils) if not x.startswith('_')])

print("imageutils loaded from:", imageutils.__file__)
print("Has aligned_capture_jp:", hasattr(imageutils, 'aligned_capture_jp'))


####
#### Aligned capture changes by Jacob Peters 
#### 
# def aligned_capture_jp(capture, warp_matrices, warp_mode, cropped_dimensions, match_index, img_type='reflectance',
#                     interpolation_mode=cv2.INTER_LANCZOS4):
#     width, height = capture.images[match_index].size()

#     im_aligned = np.zeros((height, width, len(warp_matrices)), dtype=np.float32) # change from float32 to uint16 ? warp matrices made from uint16 image. 

#     for i in range(0, len(warp_matrices)):
#         # if img_type == 'reflectance': # - Jacob changed from undistorted_reflectance. I already calibrated and undistorted images. so dont do that. 
#         #    img = capture.images[i].reflectance()
#         # else:
#         #    img = capture.images[i].radiance()


#         img = plt.imread(capture.images[i].path).astype(np.uint16) # this works, just load the image. stop messing with pixel values!!!! 


#         if warp_mode != cv2.MOTION_HOMOGRAPHY:
#             im_aligned[:, :, i] = cv2.warpAffine(img,
#                                                  warp_matrices[i],
#                                                  (width, height),
#                                                  flags=interpolation_mode + cv2.WARP_INVERSE_MAP) 
#         else:
#             im_aligned[:, :, i] = cv2.warpPerspective(img,
#                                                       warp_matrices[i],
#                                                       (width, height),
#                                                       flags=interpolation_mode + cv2.WARP_INVERSE_MAP)
#     (left, top, w, h) = tuple(int(i) for i in cropped_dimensions)
#     im_cropped = im_aligned[top:top + h, left:left + w][:]

#     return im_cropped

####
#### end of aligned_capture changes
####


import micasense.plotutils as plotutils
from skimage.transform import ProjectiveTransform
import numpy as np

from ipywidgets import FloatProgress, Layout
from IPython.display import display
import micasense.imageset as imageset
import multiprocessing
import math
import numpy as np
from mapboxgl.viz import *
from mapboxgl.utils import df_to_geojson, create_radius_stops, scale_between
from mapboxgl.utils import create_color_stops
import pandas as pd
import tifffile


import micasense_calibration as mc


parser = argparse.ArgumentParser('Align and calibrate photos.')

parser.add_argument('flight_loc', type=str, help='str, absolute path to \
	top-level directory of this flight.')
parser.add_argument('-calmodel', dest='cal_model_fn', default=None, type=str, 
	help='str, absolute path to configuration file containing calibration \
	parameters for camera used in this flight. Only needed when camera \
	firmware < 2.1.0.')
parser.add_argument('imageName', type=str, default='IMG_0005_*.tif',
                    help='image name to use for alignement.')

args = parser.parse_args()


panelNames = None
useDLS = False
write_exif_to_individual_stacks = False
overwrite = True # set to true if you want to overwrite (takes longer)
generateThumbnails = False


# start alignment process. 

imagePath = Path(args.flight_loc + 'refl/')
imageNames = list(imagePath.glob(args.imageName))
imageNames = [x.as_posix() for x in imageNames]

# panelNames = list(imagePath.glob('IMG_0000_*.tif'))
# panelNames = [x.as_posix() for x in panelNames]

# check for rig relatives
thecapture = capture.Capture.from_filelist(imageNames)

for img in thecapture.images:
    if img.rig_relatives is None:
        raise ValueError("Images must have RigRelatives tags set which requires updated firmware and calibration. See the links in text above")


# get camera model for future use 
cam_model = thecapture.camera_model
# if this is a multicamera system like the RedEdge-MX Dual,
# we can combine the two serial numbers to help identify 
# this camera system later. 
if len(thecapture.camera_serials) > 1:
    cam_serial = "_".join(thecapture.camera_serials)
    print(cam_serial)
else:
    cam_serial = thecapture.camera_serial
    
print("Camera model:",cam_model)
print("Bit depth:", thecapture.bits_per_pixel)
print("Camera serial number:", cam_serial)


# determine if this sensor has a panchromatic band
if cam_model == 'RedEdge-P' or cam_model == 'Altum-PT':
    panchroCam = True
else:
    panchroCam = False


# get panel info

if panelNames is not None:
    panelCap = capture.Capture.from_filelist(panelNames)
else:
    panelCap = None

if panelCap is not None:
    if panelCap.panel_albedo() is not None and not any(v is None for v in panelCap.panel_albedo()):
        panel_reflectance_by_band = panelCap.panel_albedo()
    else:
        panel_reflectance_by_band = [0.49]*len(panelCap.eo_band_names()) #RedEdge band_index order
    
    panel_irradiance = panelCap.panel_irradiance(panel_reflectance_by_band)    
    img_type = "reflectance"
else:
    if useDLS:
        img_type='reflectance'
    else:
        img_type = "radiance"




# find warp matrices
if panchroCam:
    warp_matrices_filename = cam_serial + "_warp_matrices_SIFT.npy"
else:
    warp_matrices_filename = cam_serial + "_warp_matrices_opencv.npy"


if Path('./' + warp_matrices_filename).is_file():
    print("Found existing warp matrices for camera", cam_serial)
    load_warp_matrices = np.load(warp_matrices_filename, allow_pickle=True)
    loaded_warp_matrices = []
    for matrix in load_warp_matrices: 
        if panchroCam:
            transform = ProjectiveTransform(matrix=matrix.astype('float64'))
            loaded_warp_matrices.append(transform)
        else:
            loaded_warp_matrices.append(matrix.astype('float32'))
    print("Warp matrices successfully loaded.")

    if panchroCam:
        warp_matrices = loaded_warp_matrices # used to be called warp_matrices_SIFT
    else:
        warp_matrices = loaded_warp_matrices
else:
    print("No existing warp matrices loaded. Are you sure you want to use rig relatives? ")
    # warp_matrices_SIFT = False
    # warp_matrices = False
    warp_matrices = None






# now align. 



# set image path here
imagePath = Path(args.flight_loc + 'refl/')

# destinations on my computer to put the aligned images
outputPath = Path(args.flight_loc + 'datasets/project/images/') # ODM looks for "datasets/project/images/" for processing. 
thumbnailPath = Path(args.flight_loc + 'thumbnails')



# Create imageset
imgset = imageset.ImageSet.from_directory(imagePath)

# print(f"imgset: {imgset}")


# Create output directories
if not os.path.exists(outputPath):
    os.makedirs(outputPath)
if generateThumbnails and not os.path.exists(thumbnailPath):
    os.makedirs(thumbnailPath)

# Save geojson data
import pandas as pd
from mapboxgl.utils import df_to_geojson

data, columns = imgset.as_nested_lists()
df = pd.DataFrame.from_records(data, index='timestamp', columns=columns)
geojson_data = df_to_geojson(df, columns[3:], lat='latitude', lon='longitude')

with open(os.path.join(outputPath, 'imageSet.json'), 'w') as f:
    f.write(str(geojson_data))




reference_band = 5
warp_mode = cv2.MOTION_HOMOGRAPHY




# Define band names for proper identification

band_names = ['Blue', 'Green', 'Red', 'NIR', 'RedEdge', 'Panchro']
band_names_original = band_names

start = datetime.datetime.now()
for i, capture in enumerate(imgset.captures):
    
    print(f"Processing capture {i+1}/{len(imgset.captures)}...")
    
    base_filename_parts = os.path.basename(os.path.splitext(capture.images[0].path)[0]).split("_", 2)
    base_filename = base_filename_parts[0] + "_" + base_filename_parts[1]
    outputFilename = f'{base_filename}.tif'
    fullOutputPath = os.path.join(outputPath, outputFilename)

    # Check if we need to process this capture
    skip_capture = True
    num_output_bands = 6  
    for j in range(num_output_bands):
        #band_name = band_names[j] if j < len(band_names) else f'Band_{j+1}' # uncomment to use band names
        band_name = f'{j+1}'
        outputFilename = f'{base_filename}_{band_name}.tif'
        fullOutputPath = os.path.join(outputPath, outputFilename)
        
        if not os.path.exists(fullOutputPath) or overwrite:
            skip_capture = False
            break
    
    if skip_capture:
        print(f"Skipping capture {i+1} - all bands already processed")
        continue
    
    # for idx, img in enumerate(capture.images):
    #     arr = img.raw()
    #     print(f"  Band {idx}: shape={arr.shape}, path={img.path}")


    # Perform alignment using rid relative tags. 
    if (not os.path.exists(fullOutputPath)) or overwrite:
        if(len(capture.images) == len(imgset.captures[0].images)):
            # print(f"capture: {capture}")
            warp_matrices = capture.get_warp_matrices(ref_index=reference_band) # images are in uint16 after calibration. 

            cropped_dimensions,edges = imageutils.find_crop_bounds(capture,warp_matrices,reference_band=reference_band)


            # now we use a version of aligned_capture that i edited so it does not do any undistortion. -- this is explained above. 
            # because i already calibrated and undistorted images in the process_flight_images_cap.py script.
            im_aligned = imageutils.aligned_capture_jp(capture, warp_matrices, warp_mode, cropped_dimensions, reference_band, img_type="reflectance")


            print("im_aligned type:", type(im_aligned))
            if isinstance(im_aligned, np.ndarray):
                print("im_aligned shape:", im_aligned.shape)
            elif isinstance(im_aligned, list):
                print("im_aligned list length:", len(im_aligned))
                print("first element shape:", np.array(im_aligned[0]).shape)
            # print("upsampled shape:", np.array(upsampled).shape)
            print("bands:", len(capture.images))

            # capture.save_capture_as_stack(fullOutputPath, pansharpen=panSharpen,sort_by_wavelength=True, write_exif=write_exif_to_individual_stacks)

            aligned_images = im_aligned # this is a numpy array of shape (height, width, bands) 


            # this all works - only thing left to maybe add is pan sharpening if you want. 
    
            
    # capture.clear_image_data()
                
    # Save each band as a separate uncompressed TIFF

    print(f"Saving aligned images for capture {i+1}/{len(imgset.captures)}...")

    rescale = False

    for j in range(aligned_images.shape[2]): #  height, width, bands
        band_data = aligned_images[:, :, j]

        print(f"Band {j+1} - Before saving: min={band_data.min()}, max={band_data.max()}")

        # check values above. I don't think we need to scale. -- if max values are around 30k-ish, we're good. 
        if rescale:
            band_data = (band_data * 32768).astype(np.uint16)
            band_data[band_data<0] = 0 # min cutoff zero
            band_data[band_data>65535] = 65535 # max cutoff 65535


            print("After scaling: min =", band_data.min(), "max =", band_data.max())
        else: 

            band_data = band_data.astype(np.uint16)
            # band_data = band_data.astype(np.float16)  # 16bit fine i think 
            # does ODM prefer decimals or integers? 

        #band_name = band_names[j] if j < len(band_names) else f'Band_{j+1}' # uncomment to use band names
        band_name =  f'{j+1}'
        outputFilename = f'{base_filename}_{band_name}.tif'
        fullOutputPath = os.path.join(outputPath, outputFilename)
        tifffile.imwrite(
            fullOutputPath,
            band_data,
            compress=0, 
            photometric='minisblack',
            metadata=None)


        # Copy metadata from the corresponding original band
        # When pan-sharpened, bands 1-5 come from original bands 1-5
        original_band_idx = j
        original_path = capture.images[original_band_idx].path

        cmd = 'exiftool %s -overwrite_original -q -tagsFromFile %s -all:xmp -all:all' %(fullOutputPath, original_path) # %s -all:EXIF -all:xmp -EXIF:BlackLevel -all:all'
 
        subprocess.call(cmd, shell=True)

        # how we did it in reflectance calibration script: 
        #cmd = 'exiftool %s -overwrite_original -q -tagsFromFile %s -all:xmp -all:all' %(filename, fl_im_name) # -all:xmp 
        ## jacob added the -all:xmp -all:all because it keeps band name and other info like irradiance from dls # this makes some duplicates but shouldn't matter ... I hope. 
        ## but we need to make sure we keep utc date time .... 
        #subprocess.call(cmd, shell=True)


        # black level was really tricky. 
        # to find it, I had to run exiftool -v2 -BlackLevel file.tif
        # and found that it was in the ifd0:BlackLevel and ifd0:BlackLevelRepeatDim tags.
            # could also use -0xc61a -0xc619 , but the below works and seems more robust than a code. 
        # cmd2 = 'exiftool %s -overwrite_original -q -tagsFromFile %s -ifd0:BlackLevel -ifd0:BlackLevelRepeatDim' % (fullOutputPath, original_path)
        # subprocess.call(cmd2, shell=True) # not totally sure I still need this. remove for now. If I get corrupted error in ODM, try it. 
  
    
    # Clear memory
    capture.clear_image_data()

end = datetime.datetime.now()

print("Processing time: {}".format(end-start))
print("Alignment+Saving rate: {:.2f} captures per second".format(float(len(imgset.captures))/float((end-start).total_seconds())))
