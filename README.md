# micasense_calibration
Tweaks to micasense calibration for my UAV workflow. 


# notes

need to calibrate reflectance and align bands before uploading to ODM. Repos from two sources. 

    * Started here: https://micasense.github.io/imageprocessing/MicaSense%20Image%20Processing%20Setup.html
    * Then here: https://micasense.github.io/imageprocessing/MicaSense%20Image%20Processing%20Tutorial%201.html

# workflow


## Connect to VPN and Mount Drives

First, in my case, I need to connect to my university's VPN and mount my network drives. 

```
    echo CONNECT TO VPN!!!!

    # or run this - i made a handy shell script to do it. 
    ~/mount-drives.sh
```


## Working Directory

Now I reset my working directory. 
I have a tempWorkingDir folder on my computer that I work from and then clear after each mission. 

```
# reset 
	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir
	rm -r ./images_copyTo_dontTouch/*
	rm -r ./raw/*
	rm -r ./refl/*
	rm -r ./datasets/*
	rm -r ./products/*
```

These folders each have a purpose: 
    * **images_copyTo_dontTouch**: this is where the raw images are stored and i, obviously, don't touch them. 
    * **raw**: this is where i copy the images to and then start working. 
    * **refl**: this is where calibrated and undistorted images are saved. 
    * **datasets**: this is where OpenDroneMap looks for my project. Aligned multispectral photos are saved here. 
    * **products**: this is where the final products are moved to. Mainly, that's the orthomosaic. 

The structure looks like this, if the datasets/project/ directory hasn't been cleared: 

```

├── datasets
│   └── project
│       ├── images
│       ├── odm_dem
│       ├── odm_filterpoints
│       ├── odm_georeferencing
│       ├── odm_meshing
│       ├── odm_orthophoto
│       ├── odm_report
│       ├── odm_texturing_25d
│       │   ├── blue
│       │   ├── green
│       │   ├── nir
│       │   ├── red
│       │   └── rededge
│       └── opensfm
│           ├── exif
│           ├── features
│           ├── matches
│           ├── reports
│           │   └── features
│           ├── stats
│           └── undistorted
│               └── images
├── images_copyTo_dontTouch
├── products
├── raw
├── refl
└── z_imagesForWarpMatrices
    ├── raw
    └── refl
```

---

## Set Up Mission-Specific Objects

Now I need to update a few objects that this script / workflow uses. 
This might vary depending on your particular data management. 
For me, I have a site name that is consistent, a missionFolder directory, a missionPath, and a flightDir. 
Sometimes I have multiple missions at each site, and I need to pick the best one. 

```
	# UPDATE flight# folder

	missionFolder='20250629_coyoteCove'  # name of mission
	siteName='coyoteCove' # site name 
	missionPath='images' # where are the images we want inside that mission
	flightDir='flight4'  # which flight # is it? if relevant. defaults to flight1 i guess for missions with one flight. 

```


---

## Copy files

```
# copy files from where ever. 
	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir

	find "/media/U/drones/_missions/$missionFolder/$missionPath/$flightDir/" -name "*.tif" -print0 | rsync -avmP --no-relative --files-from=- --from0 / ./images_copyTo_dontTouch/

	echo "rsync to temp working directory complete."



	# sometimes we get corrupted images. check and then rsync those again if needed. 
	# they would be missing band name

	# After initial rsync, run verification loop:
	echo "Verifying copied files..."
	max_retries=3
	retry_count=0

	# First run - check all files
	while IFS= read -r -d '' file; do
	files_to_check+=("$file")
	done < <(find ./images_copyTo_dontTouch/ -name "*.tif" -print0)

	while [ $retry_count -lt $max_retries ]; do
		corrupted_files=()
		file_count=0
		# Check each .tif file for proper band naming
		while IFS= read -r -d '' file; do

			((file_count++))
        
			# Print a dot every file, newline every 50 files
			printf "."
			if [ $((file_count % 50)) -eq 0 ]; then
				printf " %d\n" $file_count
			fi

			filename=$(basename "$file")
        
			# Check if Band Name metadata exists
			band_name=$(exiftool -s -s -s -BandName "$file" 2>/dev/null)
			if [ -z "$band_name" ]; then
				printf "\nMissing band name: $filename\n"
				corrupted_files+=("$file")
			fi

		done < <(find ./images_copyTo_dontTouch/ -name "*.tif" -print0)
		
		if [ ${#corrupted_files[@]} -eq 0 ]; then
			echo "All files verified successfully!"
			break
		fi
		
		echo "Found ${#corrupted_files[@]} corrupted files, retry $((retry_count + 1))/$max_retries"
		
		# Remove corrupted files and re-rsync them
		for file in "${corrupted_files[@]}"; do
			rm "$file"
			echo "Removed: $(basename "$file")"
		done
		
		# Re-rsync
		find "/media/U/drones/_missions/$missionFolder/$missionPath/$flightDir/" -name "*.tif" -print0 | rsync -avmP --no-relative --files-from=- --from0 / ./images_copyTo_dontTouch/
		# Next iteration only checks the files that were corrupted
		files_to_check=("${corrupted_files[@]}")
		
		((retry_count++))
	done
```

---

## Update Image Names and Check Images

Now we can get panelImage objects and check a test image. 

```

# UPDATE image names
	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir


	# now get an example image. get the base name of the 10th file (to avoid panels)
	imageName=$(ls /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir/images_copyTo_dontTouch/*.tif | grep -v panel | awk 'NR==25' | xargs basename | sed 's/_[0-9]*\.tif$/_*.tif/')
	echo "image reference: $imageName"

	# check first and last images irradiance
	echo "first image" && exiftool -directirradiance ./images_copyTo_dontTouch/*.tif | head -13
	echo "last image" && exiftool -directirradiance ./images_copyTo_dontTouch/*.tif | tail -13


	# CHECK PANEL IMAGES ........ 
	exiftool -directirradiance ./images_copyTo_dontTouch/IMG_0000_*.tif
	exiftool -directirradiance ./images_copyTo_dontTouch/IMG_0001_*.tif
	exiftool -directirradiance ./images_copyTo_dontTouch/IMG_0002_*.tif


	# grab before and after panel
	panelImage='IMG_0000_*.tif' # need it to be like "IMG_XXXX_*.tif" it will default to IMG_0000_*.tif
	# can automatically choose last panel 
	panelImage_post=$(ls /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir/images_copyTo_dontTouch/*.tif | tail -5 | head -1 | xargs basename | sed 's/_[0-9]*\.tif$/_*.tif/')
    # or specify 
	# panelImage='IMG_0131_*.tif'
	echo "post-flight panel: $panelImage_post"
	echo "panel reference: $panelImage"


	# check irradiance and decide if you've got any photos that don't belong. 
	# sunny values usually are like 80+
	# cloudy values usually are like 20. 
	exiftool -directirradiance ./images_copyTo_dontTouch/*_3.tif
	echo "Compare to panel image (pre and post): "
	exiftool -directirradiance ./images_copyTo_dontTouch/$panelImage*
	exiftool -directirradiance ./images_copyTo_dontTouch/$panelImage_post



```

---

## Set up Processing Directory

Now simply set up my directories. 

```

# set up processing directory stuff.  
	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir
	source activate micasense
	mkdir raw # raw photos
	mkdir refl # calibrated reflectance 
	mkdir datasets
	mkdir datasets/project # odm project folder
	mkdir datasets/project/images # where final aligned images go
	mkdir products # where odm outputs get organized to. Used later. 
	cp -a images_copyTo_dontTouch/. raw/ # copy images to raw folder. cp -a will preserve metadata etc. 
	echo "copying to raw image folder complete."


	# set up python
	export PYTHONPATH=/mnt/hdd/Dropbox/cloned_repos/imageprocessing:/mnt/hdd/Dropbox/cloned_repos/jacobs_micasense_calibration

```

---

## Reflectance Calibration

I have another repo with the scripts I need for reflectance calibration and alignment, based on the two github repos noted at the top of this readme. 

That directory looks like this: 

```

jacobs_micasense_calibration
├── alignment_processing_rigRelatives.py
├── LICENSE
├── panel_RP02-1603157-SC.csv
├── panel_values.csv
├── process_flight_images_cap_autoPanel_DLS.py
└── README.md

```

So run reflectance calibration... 

Note that I've had some problems with the DLS. At recent YMF drone zone flight, I had to skip it. 


```
# reflectance - correct lens distortion, correct per dls irradiance, convert to reflectance using panels and DLS. 

	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir
	/mnt/hdd/Dropbox/cloned_repos/jacobs_micasense_calibration//process_flight_images_cap_autoPanel_DLS.py \
    /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir/ \
    $imageName \
    panel_values.csv \
    $panelImage \
    --use_dls always \
    --panelName_post "$panelImage_post"  # Add this if we have a post panel
	
	
	# --use.dls options are 'always' 'auto' or 'never'
	# default imageName is 'IMG_0005_*.tif'  # default panelName is 'IMG_0000_*'
	echo "reflectance calibration complete."

```


## Remove Panel Images and Align Multispectral Bands

Remember that the alignment script will put images directly where OpenDroneMap wants them to go. 

```


	# remove panel images trigger method = 0 for these manually triggered photos. 
    # Remove all images with TriggerMethod = 0 (manual trigger)

	echo "Removing panel images (manual trigger) from ./refl/..."
	cd ./refl/
	count=0
	for f in *.tif; do
		trigger=$(exiftool -s -s -s -TriggerMethod "$f" 2>/dev/null)
		if [[ "$trigger" == "0" ]]; then
			echo "  Removing: $f"
			rm "$f"
			((count++))
		fi
	done
	echo "Removed $count panel images"
	cd ..


	# alignment -- after calibration. 
	/mnt/hdd/Dropbox/cloned_repos/micasense_calibration/alignment_processing_rigRelatives.py /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir/ $imageName # default imageName is 'IMG_0005_*.tif'


	cd /mnt/hdd/Dropbox/SpatialData/droneData/tempWorkingDir/
	echo "Aligned photos should be available in ./datasets/project/images/"
	ls ./datasets/project/images/


```


---


## OpenDroneMap 

This isn't the point of this repo, but I feel it's worth including that I run these images through ODM at the end of all this. After, I use rsync to send them wherever they need to go. 

### Process 

```




	# ODM 
	docker pull opendronemap/odm
	docker run -ti --rm -v /$(pwd)/datasets:/datasets opendronemap/odm --project-path /datasets project \
	--feature-quality high \
	--auto-boundary \
	--pc-quality high \
	--primary-band Panchro \
	--cog \
	--texturing-skip-global-seam-leveling \
	--fast-orthophoto \
	--orthophoto-resolution 2.5 \

	
	# things you might want: # --orthophoto-resolution 1-3 ? # instead of default 5. # --dem-resolution 1-2 # --pc-geometric # might help for forest? # setting feature and pc quality to high seems better than ultra. # for visuals' sake we might want to set crop to like 20m instead of default 3. 
	# also maybe we let it do alignment? just to see if it improves atop rig relatives? It does, and we do want that. 
	# idk why but since Nov 2025 i havent been able to get it to give me dsm and dtm. oh well. just took those out. 

	# if we're pan sharpening, maybe use higher res? like aim for 2.5cm? 
	
	# change ownership of our files to us and copy to our products folder 
	sudo chown -R $USER:$USER ./datasets/project
	cp -a ./datasets/project/odm_orthophoto/odm_orthophoto.tif ./products/ # copy orthophoto to products
	cp -a ./datasets/project/odm_dem/dsm.tif ./products/ # copy dsm to products
	cp -a ./datasets/project/odm_dem/dtm.tif ./products/ # copy dtm to products-

```


### Normalize Brightness

```

	# normalize brightness? this is new as of july 2025 ... can make for better visuals but not analysis. 
	/mnt/hdd/Dropbox/cloned_repos/micasense_calibration/postProcess_normalization.py ./products/odm_orthophoto.tif ./products/odm_orthophoto_normalized.tif 

	
	# options: --pansharpen --no-normalize 
	# default is to normalize and not pan sharpen. 

	echo "odm processing and mosaic normalization complete."
```

### rsync products to where they need to be

```

	# rsync products back to mission folder -- products first so we can peek sooner! 
	mkdir -p /media/U/drones/_missions/$missionFolder/processedImages/products/$flightDir
	# move products to U drive mission folder
	rsync -avP -r --chown=$USER:$USER ./products/odm_orthophoto_normalized.tif /media/U/drones/_missions/$missionFolder/processedImages/products/$flightDir/

```


---

## Clear Directories

Now that I'm done, I usually run this to clear things. 

If not, no big deal. I clear them at the top of the workflow too! 

```

	# clear tempWorkingDir folders raw/ refl/ images_copyTo_dontTouch/ images/ datasets/ 
	rm -r ./raw/*
	rm -r ./refl/*
	rm -r ./images_copyTo_dontTouch/*
	rm -r ./datasets/*
	rm -r ./products/*
	echo "tempWorkingDir cleared." 

```