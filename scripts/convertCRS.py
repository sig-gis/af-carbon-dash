import geopandas as gpd
import os

# Input shapefile path
in_path = r"C:\Users\edalt\PC585_AF\data\FVSVariantMap20210525\FVS_Variants_and_Locations.shp"

# Output folder & filename
out_folder = r"C:\Users\edalt\PC585_AF\data\FVSVariantMap20210525"
out_file = "FVS_Variants_and_Locations_4326.shp"
out_path = os.path.join(out_folder, out_file)

# Load shapefile (should be in ESRI:102039)
gdf = gpd.read_file(in_path)

print("Original CRS:", gdf.crs)

# Reproject to WGS84 (EPSG:4326)
gdf_4326 = gdf.to_crs(epsg=4326)

# Save new shapefile
gdf_4326.to_file(out_path, driver="ESRI Shapefile")

print(f"Reprojected shapefile saved to: {out_path}")
print("New CRS:", gdf_4326.crs)
