# ---------------------------------------------------------
# Makefile for preparing GeoJSON for Streamlit dashboard
# ---------------------------------------------------------

# Configuration
URL = https://www.fs.usda.gov/fmsc/ftp/fvs/docs/overviews/FVSVariantMap20210525.zip
ZIP = tmp/my_shapefile.zip
SHP = tmp/shapefile/FVS_Variants_and_Locations.shp
FINAL_GEOJSON = data/FVSVariantMap20210525/FVS_Variants_and_Locations_4326_simplified.geojson

# Default target
all: $(FINAL_GEOJSON)

$(FINAL_GEOJSON):
	@echo "GeoJSON missing. Running pipeline..."
	python scripts/downloadFile.py $(URL) $(ZIP) $(SHP)
	python scripts/convertGeoJSON.py --input $(SHP) --output $(FINAL_GEOJSON)
	@echo "Pipeline complete. GeoJSON exported to $(FINAL_GEOJSON)"

clean:
	python -c "import shutil; shutil.rmtree('tmp', ignore_errors=True); shutil.rmtree('data/final', ignore_errors=True)"

.PHONY: all clean