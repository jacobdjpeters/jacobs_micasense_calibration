#!/usr/bin/env python
import numpy as np
from osgeo import gdal
from scipy.ndimage import gaussian_filter
import subprocess
import os

def normalize_orthophoto_brightness(input_path, output_path, sigma=100, max_correction=1.5, brightness_adjust=1.0):
    """
    Post-process orthophoto to reduce large-scale brightness variations
    while preserving fine details for species classification
    
    Args:
        input_path: Path to input orthophoto
        output_path: Path for output normalized orthophoto
        sigma: Gaussian filter size (pixels) for detecting large-scale patterns
        max_correction: Maximum correction factor to apply
        brightness_adjust: Overall brightness adjustment (1.0 = no change)
    """
    
    # Open the orthophoto
    ds = gdal.Open(input_path)
    if ds is None:
        raise ValueError(f"Could not open {input_path}")
    
    # Check if we need BigTIFF (file size > 3GB to be safe)
    width = ds.RasterXSize
    height = ds.RasterYSize
    bands = ds.RasterCount
    estimated_size = width * height * bands * 2 / (1024**3)  # Size in GB for uint16
    # Get input file size for comparison
    input_size_gb = os.path.getsize(input_path) / (1024**3)
    
    
    # Use BigTIFF if:
    # 1. Estimated size > 2GB (more conservative threshold)
    # 2. Input file is already large (>1.0GB)
    # 3. Very large dimensions (>50k pixels in any dimension)
    if estimated_size > 2.0 or input_size_gb > 1.0 or width > 50000 or height > 50000:
        create_options = ['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES', 'BLOCKXSIZE=512', 'BLOCKYSIZE=512']
        print(f"Using BigTIFF format with 512x512 blocks")
    else:
        create_options = ['COMPRESS=LZW', 'TILED=YES', 'BLOCKXSIZE=512', 'BLOCKYSIZE=512']
    
    
    
    # Create output dataset
    driver = gdal.GetDriverByName('GTiff')
    out_ds = driver.Create(output_path, 
                           ds.RasterXSize, 
                           ds.RasterYSize, 
                           ds.RasterCount, 
                           gdal.GDT_UInt16,
                           options=create_options)
    
    # Copy geotransform and projection
    out_ds.SetGeoTransform(ds.GetGeoTransform())
    out_ds.SetProjection(ds.GetProjection())
    
    # Copy metadata
    metadata = ds.GetMetadata()
    if metadata:
        out_ds.SetMetadata(metadata)
    
    # Process each band
    for band_idx in range(1, ds.RasterCount + 1):
        print(f"Processing band {band_idx}/{ds.RasterCount}")
        
        # Read band
        band = ds.GetRasterBand(band_idx)
        data = band.ReadAsArray().astype(np.float32)
        
        # Get nodata value
        nodata = band.GetNoDataValue()
        if nodata is not None:
            mask = (data != nodata)
        else:
            # Assume 0 is nodata for orthophotos
            mask = (data > 0)
        
        # Extract valid data for statistics
        valid_data = data[mask]
        
        if len(valid_data) == 0:
            print(f"Warning: Band {band_idx} has no valid data")
            out_band = out_ds.GetRasterBand(band_idx)
            out_band.WriteArray(data.astype(np.uint16))
            if nodata is not None:
                out_band.SetNoDataValue(nodata)
            continue
        
        # Create a padded version for filtering to avoid edge artifacts
        # Replace nodata with median value for filtering only
        median_val = np.median(valid_data)
        data_for_filter = np.where(mask, data, median_val)
        
        # Apply gaussian filter to get low-frequency component
        low_freq = gaussian_filter(data_for_filter, sigma=sigma)
        
        # Avoid division by zero
        low_freq[low_freq < median_val * 0.1] = median_val * 0.1
        
        # Calculate correction factor
        correction = median_val / low_freq
        
        # Limit correction to reasonable range
        correction = np.clip(correction, 0.5, max_correction)
        
        # Apply overall brightness adjustment
        correction = correction * brightness_adjust
        
        # Apply correction only to valid pixels
        corrected_data = data.copy()
        corrected_data[mask] = data[mask] * correction[mask]
        
        # Clip to valid range
        corrected_data = np.clip(corrected_data, 0, 65535).astype(np.uint16)
        
        # Restore original nodata values
        if nodata is not None:
            corrected_data[~mask] = nodata
        
        # Write to output
        out_band = out_ds.GetRasterBand(band_idx)
        out_band.WriteArray(corrected_data)
        if nodata is not None:
            out_band.SetNoDataValue(nodata)
            
        # Copy band metadata
        band_metadata = band.GetMetadata()
        if band_metadata:
            out_band.SetMetadata(band_metadata)
            
        # Copy band description
        description = band.GetDescription()
        if description:
            out_band.SetDescription(description)
            
        out_band.FlushCache()
    
    # Close datasets
    ds = None
    out_ds = None
    
    print("Normalization complete!")
    
    # Try to copy additional metadata with exiftool if not BigTIFF
    try:
        # Check if output is BigTIFF
        info = gdal.Info(output_path, format='json')
        if 'BIGTIFF' not in str(info):
            print("Copying additional metadata with exiftool...")
            cmd = f'exiftool {output_path} -overwrite_original -q -tagsFromFile {input_path} -all:all'
            subprocess.call(cmd, shell=True)
            print("Additional metadata copied successfully!")
        else:
            print("Note: BigTIFF format - metadata copied via GDAL only")
    except:
        print("Note: Metadata copied via GDAL only")

# Usage example
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python normalize_brightness.py <input_path> <output_path> [sigma] [max_correction] [brightness_adjust]")
        print("Example: python normalize_brightness.py ./products/odm_orthophoto.tif ./products/odm_orthophoto_normalized.tif 100 1.5 0.9")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    sigma = int(sys.argv[3]) if len(sys.argv) > 3 else 100
    max_correction = float(sys.argv[4]) if len(sys.argv) > 4 else 1.5
    brightness_adjust = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
    
    print(f"Normalizing {input_path} -> {output_path}")
    print(f"Parameters: sigma={sigma}, max_correction={max_correction}, brightness_adjust={brightness_adjust}")
    normalize_orthophoto_brightness(input_path, output_path, sigma, max_correction, brightness_adjust)