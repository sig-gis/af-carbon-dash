# ---------------------------------------------------------
# Makefile for preparing GeoJSON for Streamlit dashboard
# ---------------------------------------------------------

# Configuration
URL = https://www.fs.usda.gov/fmsc/ftp/fvs/docs/overviews/FVSVariantMap20210525.zip
MAKE_TMP ?= tmp
ZIP = $(MAKE_TMP)/FVSVariantMap20210525.zip
SHPDIR = $(MAKE_TMP)/shapefile
SHP = $(SHPDIR)/FVS_Variants_and_Locations.shp
FINAL_GEOJSON = data/FVSVariantMap20210525/FVS_Variants_and_Locations_4326_simplified.geojson
SUPPORTED_VARIANTS = conf/base/supported_variants.txt

# Read variant codes (one per line; ignore blanks/#; strip CR)
KEEP_VARIANTS := $(shell sed -e 's/#.*//' -e '/^[[:space:]]*$$/d' -e 's/\r//' $(SUPPORTED_VARIANTS) 2>/dev/null | xargs)
ifneq ($(strip $(KEEP_VARIANTS)),)
  KEEP_ARGS = --keep-variants $(KEEP_VARIANTS)
endif

.DELETE_ON_ERROR:
.PHONY: all clean rebuild

# Default target
all: $(FINAL_GEOJSON)

# Rebuild if scripts or variant list change
$(FINAL_GEOJSON): scripts/downloadFile.py scripts/convertGeoJSON.py $(SUPPORTED_VARIANTS)
	@echo "==> Preparing $@"
	@mkdir -p $(dir $@) $(SHPDIR)
	python3 scripts/downloadFile.py $(URL) $(ZIP) $(SHP)
	python3 scripts/convertGeoJSON.py --input $(SHP) --output $(FINAL_GEOJSON) $(KEEP_ARGS)
	@echo "==> Cleaning intermediates"
	@rm -rf $(MAKE_TMP)
	@echo "==> Done. Kept: $(FINAL_GEOJSON)"
	@$(if $(strip $(KEEP_VARIANTS)), \
		echo "Kept variants: $(KEEP_VARIANTS)";, \
		echo "No keep-variants specified (kept all)";)

clean:
	@echo "Removing final output (keeps nothing)..."
	@rm -f $(FINAL_GEOJSON)

rebuild: clean all
