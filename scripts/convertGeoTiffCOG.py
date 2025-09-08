import os
import rasterio
from rasterio.shutil import copy
from rasterio.enums import Resampling

# Input and output paths
src_path = r"C:\Users\edalt\PC585_AF\af-carbon-dash\data\final\RDS-2020-0016-2__BP_CONUS\BP_CONUS\BP_CONUS.tif"
dst_path = r"C:\Users\edalt\PC585_AF\af-carbon-dash\data\final\RDS-2020-0016-2__BP_CONUS\BP_CONUS\BP_CONUS_COG.tif"

# Convert to Cloud Optimized GeoTIFF
copy(
    src_path,
    dst_path,
    driver="COG",
    copy_src_overviews=True,
    compress="LZW",
    BIGTIFF="YES",  # force BigTIFF
    overview_resampling=Resampling.nearest
)
