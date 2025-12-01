#! /usr/bin/env python
"""
Driver script for a flight bounded by reflectance panels pre- and post-flight.
Jacob P: this should be run before the flight images have been aligned in alignment_processing_rigRelatives.py. 
"""

import matplotlib.pyplot as plt
import micasense.capture as capture
import micasense.dls as dls
import micasense.image as image
import micasense.panel as panel
import pandas as pd
import glob
#from libtiff import TIFFimage
import tifffile 
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
import math
import warnings

#%matplotlib inline
from pathlib import Path
plt.rcParams["figure.facecolor"] = "w"
import cv2
import time
import numpy as np
import matplotlib.pyplot as plt
import micasense.imageutils as imageutils
import micasense.utils as msutils
import micasense.plotutils as plotutils
from skimage.transform import ProjectiveTransform
import numpy as np

from ipywidgets import FloatProgress, Layout
from IPython.display import display
import micasense.imageset as imageset
import multiprocessing

import micasense_calibration as mc

from pysolar.solar import get_altitude
from pytz import timezone

parser = argparse.ArgumentParser('Calibrate and correct all RedEdge images \
	acquired in a flight. ')

parser.add_argument('flight_loc', type=str, help='str, absolute path to \
	top-level directory of this flight.')
parser.add_argument('imageName', type=str, default='IMG_0005_*.tif',
                    help='image name to use for alignement.')
parser.add_argument('panel', type=str, help='str, absolute path to CSV file \
	containing calibration factors for your reflectance panel.')
parser.add_argument('panelName', type=str, default='IMG_0000_*.tif', help='str, filename for pre-flight \
 set of images of reflectance panel, ending before band number. \
 e.g. IMG_0000_')
parser.add_argument('--panelName_post', type=str, default=None, 
                    help='Optional: filename for post-flight panel images (e.g., IMG_9999_*.tif)')
parser.add_argument('--use_dls', type=str, default='auto', 
                    choices=['auto', 'always', 'never'],
                    help='DLS usage: auto (use with fallback), always (force DLS), never (panel only)')


args = parser.parse_args()

	
# start process. 
from micasense.image import Image
from micasense.panel import Panel

imagePath = Path(args.flight_loc + 'raw/')
imageNames = list(imagePath.glob(args.imageName))
imageNames = [x.as_posix() for x in imageNames]
thecapture = capture.Capture.from_filelist(imageNames)

print(f"panel name: {args.panelName}")
panelNames = glob.glob(os.path.join(imagePath, args.panelName))

print(f"panel names found: {panelNames}")


# panelNames = list(imagePath.glob(args.panelName))
# print(f"panel names found: {panelNames}")
# panelNames = [x.as_posix() for x in panelNames]
# print(f"Panel names: {panelNames}")
panelCap = capture.Capture.from_filelist(panelNames)

for img in panelCap.images: 
    panel = Panel(img)

    # panel.plot() # can plot to check each image. 

    if not panel.panel_detected():
        raise IOError("Panel Not Detected!")
        
    # print("Detected panel serial: {}".format(panel.serial))
    mean, std, num, sat_count = panel.raw()
    print("Extracted Panel Statistics:")
    print("Mean: {}".format(mean))
    print("Standard Deviation: {}".format(std))
    print("Panel Pixel Count: {}".format(num))
    print("Saturated Pixel Count: {}".format(sat_count))

    



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




# try calibrating the reflectance.

# calculate dls irradiance values for the panel images
print(f"panel dls irradiances: ", panelCap.dls_irradiance()) # this will calculate the irradiance values for the panel images. 

# get the panel factors from the panel CSV file
panel_calibration = mc.load_panel_factors(args.panel)
panel_calibration = pd.DataFrame(panel_calibration)
print(panel_calibration)

# Extract the factor column as reflectances_by_band
panel_reflectance_by_band = panel_calibration['factor'].tolist()
print("Panel reflectances by band:", panel_reflectance_by_band)

panel_radiances = np.array(panelCap.panel_radiance()) # detect panels!
irr_from_panel = math.pi * panel_radiances / panel_reflectance_by_band

if args.use_dls == 'never':
    # Don't use DLS at all - set correction to 1.0 (no correction)
    dls_correction = np.ones(len(panel_radiances))
    print("Panel-only mode: No DLS correction applied")
else:
    # Original behavior - calculate DLS correction
    dls_correction = irr_from_panel/panelCap.dls_irradiance()
    print(f"DLS correction factors: {dls_correction}")



print(f"Panel radiances: {panel_radiances}")
print(f"DLS correction factors: {dls_correction}")



if args.panelName_post:
    panelNames_post = glob.glob(os.path.join(imagePath, args.panelName_post))
    if panelNames_post:
        panelCap_post = capture.Capture.from_filelist(panelNames_post)
        # Process post panel similar to pre panel
        panel_radiances_post = np.array(panelCap_post.panel_radiance())
        irr_from_panel_post = math.pi * panel_radiances_post / panel_reflectance_by_band

        if args.use_dls == 'never':
            dls_correction_post = np.ones(len(panel_radiances_post))
        else:
            dls_correction_post = irr_from_panel_post / panelCap_post.dls_irradiance()
        
        print(f"Post-flight panel radiances: {panel_radiances_post}")
        print(f"Post-flight DLS correction factors: {dls_correction_post}")
        
        # Get timestamps for interpolation
        panel_pre_time = panelCap.images[0].utc_time
        panel_post_time = panelCap_post.images[0].utc_time



# Get acquisition times for interpolation
if args.panelName_post:
    # Get pre-flight panel time (first image time)
    panel_pre_time = panelCap.images[0].utc_time
    # Get post-flight panel time  
    panel_post_time = panelCap_post.images[0].utc_time



# load images in
images = glob.glob(args.flight_loc + 'raw/*.tif', recursive=True)



overwrite = True




# if refl images are present already, skip this part
reflPath = Path(args.flight_loc + 'refl/')

# these will return lists of image paths as strings 
reflImageNames = list(reflPath.glob(args.imageName))

if overwrite or len(reflImageNames) <1:

    # Generate copy of directory structure under refl/
    for dirpath, dirnames, filenames in os.walk(args.flight_loc + 'raw/'):
        structure = os.path.join(args.flight_loc + 'refl/', 
        				dirpath[len(args.flight_loc + 'raw/'):])
        if not os.path.isdir(structure):
            os.mkdir(structure)

    n = 1
    total_im = len(images)
    for fl_im_name in images:
        print('%s / %s (%s)' %(n, total_im, fl_im_name))

        cap = capture.Capture.from_filelist([fl_im_name]) # load in capture for getting DLS irradiance values. 

        # Load image and metadata
        fl_im_raw = plt.imread(fl_im_name) # file name for raw image. 
        meta = mc.load_metadata(fl_im_name) # get metadata for this image. 


        # Add calibration model metadata
        if not mc.check_firmware_version(meta):
            meta = mc.add_cal_metadata(meta, args.cal_model_fn)

        band = meta.get_item('XMP:BandName')
        # acq_time = datetime.datetime.strptime(meta.get_item('EXIF:CreateDate'),
        #                                  '%Y:%m:%d %H:%M:%S')
        # # Convert acquisition time to julian to do time-dependent interpolation
        # acq_time_julian = pd.Series([0], index=[acq_time]).index \
        #     .to_julian_date().values

        # # Calculate rad2refl factor
        # m = refl_factors.loc[band, 'm']
        # c = refl_factors.loc[band, 'c']
        # # rad2refl = m * acq_time_julian + c # ok i dont think we should do this. 
        # # if anything, just use the mean between the pre and post flight panel factors. 
        # rad2refl = (refl_factors.loc[band, 'p1'] + refl_factors.loc[band, 'p2']) / 2


        # or just use the panel factors if they're really similar (like the same panel!). 
        # if within 2% of each other, just use the pre-flight panel factor. 
        # if abs(refl_factors.loc[band, 'p1'] - refl_factors.loc[band, 'p2']) <= 0.02 * ((refl_factors.loc[band, 'p1'] + refl_factors.loc[band, 'p2']) / 2):
        #     print(f"Using pre-flight panel factor for band {band} as p1 and p2 are within 2% of each other.")
        #     # if the pre- and post-flight panel factors are the same, use that.
        #     # this is the case for most flights, so we can just use the p1 value.
        #     rad2refl = refl_factors.loc[band, 'p1']


        # print raw radiance values before any corrections. 
        print(f"radiance before corrections: {fl_im_raw.min()} to {fl_im_raw.max()}")


        # #OLD / NOT NEEDED: Apply corrections/conversions # keeping for reference: 
        #    # if we do this, i dont think we can also run the DLS stuff below. 
        #    # because both functions try to undistort the image and we only want to do that once... 

        # get the band index for this image: 
        band_names = thecapture.eo_band_names()
        band_index = band_names.index(band)
     
     
        ## print dls irradiance values for this band.
        print(f"DLS Irradiance for band {band} ({band_index}): {cap.dls_irradiance()} ")
        

        # Get the correction factor for this specific band
        band_dls_correction = dls_correction[band_index]

        if args.panelName_post:
            band_dls_correction_post = dls_correction_post[band_index]


        for img in cap.images:
            # Get current image timestamp if we're doing interpolation
            if args.panelName_post:
                img_time = img.utc_time
                time_fraction = (img_time - panel_pre_time) / (panel_post_time - panel_pre_time)
                time_fraction = np.clip(time_fraction, 0, 1)
                
                # Interpolate panel-based irradiance
                interpolated_panel_irr = (irr_from_panel[band_index] * (1 - time_fraction) + 
                                        irr_from_panel_post[band_index] * time_fraction)
                
                # Interpolate DLS correction factor too
                interpolated_dls_correction = (band_dls_correction * (1 - time_fraction) + 
                                            band_dls_correction_post * time_fraction)
            else:
                # No interpolation - use pre-flight values
                interpolated_panel_irr = irr_from_panel[band_index]
                interpolated_dls_correction = band_dls_correction
            
            # Now apply the DLS mode with interpolated values
            if args.use_dls == 'never':
                # Panel-only mode
                dls_irr = interpolated_panel_irr / interpolated_dls_correction
                print(f"Using panel-only mode: {dls_irr:.4f}")
                if args.panelName_post:
                    print(f"  (time interpolated, fraction: {time_fraction:.2f})")
                    
            elif args.use_dls == 'always':
                # Force DLS usage
                dls_irr = cap.dls_irradiance()[0]
                
            else:  # 'auto' mode
                dls_irr = cap.dls_irradiance()[0]
                
                if dls_irr <= 0 or dls_irr > 1.3:
                    print(f"WARNING: Invalid DLS ({dls_irr:.4f}) for {fl_im_name}")
                    # Fallback to interpolated panel value
                    fallback_irr = interpolated_panel_irr / interpolated_dls_correction
                    print(f"Using panel-based fallback: {fallback_irr:.4f}")
                    dls_irr = fallback_irr
                
            
            # Apply the correction
            if args.use_dls == 'never':
                # For panel-only, dls_irr already includes the correction
                fl_im_refl = img.undistorted_reflectance(dls_irr)
            else:
                # For DLS modes, apply the correction factor
                fl_im_refl = img.undistorted_reflectance(dls_irr * interpolated_dls_correction)
                print(f"Band {band}: DLS={dls_irr:.4f}, Correction={interpolated_dls_correction:.4f}")
                print(f"Final irradiance: {dls_irr * interpolated_dls_correction:.4f}")


        print(f"reflectance after corrections, before scaling: {fl_im_refl.min()} to {fl_im_refl.max()}") # should be between 0 and 1.


        # scale and convert. 
        # Scale first
        fl_im_refl = fl_im_refl * 32768

        #Clip to uint16 range
        fl_im_refl = np.clip(fl_im_refl, 0, 65535)

        #Then convert to uint16
        fl_im_refl = fl_im_refl.astype(np.uint16)

        print(f"reflectance after corrections and scaling: {fl_im_refl.min()} to {fl_im_refl.max()}") # should be between 0 and ~32k.

        # Save reflectance image
        filename = args.flight_loc + 'refl/' + fl_im_name.split(args.flight_loc + 'raw/')[1]
        tifffile.imwrite(filename, 
                         fl_im_refl, 
                        compress=0,
                        photometric='minisblack',
                        dtype=np.uint16)


        # Copy metadata from raw image to reflectance image
        cmd = 'exiftool %s -overwrite_original -q -tagsFromFile %s -all:xmp -all:all' %(filename, fl_im_name) # -all:xmp 
        # jacob added the -all:xmp -all:all because it keeps band name and other info like irradiance from dls # this makes some duplicates but shouldn't matter ... I hope. 
        # but we need to make sure we keep utc date time .... 
        subprocess.call(cmd, shell=True)




        
        # Increment display counter
        n += 1
else: 
    print(f"skipping reflectance calibration. Refl images already exist in ", reflPath)










