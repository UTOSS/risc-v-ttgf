PYTHON ?= python3
SCRIPT := generate_module_floorplan.py
REPORTS := \
	module_floorplan_depth1_cells.svg \
	module_floorplan_depth1_tiles.svg \
	module_floorplan_depth2_cells.svg \
	module_floorplan_depth2_tiles.svg \
	summary.json \
	summary.md

.PHONY: all reports clean

all: reports

reports: $(REPORTS)

$(REPORTS): $(SCRIPT)
	$(PYTHON) $(SCRIPT)

clean:
	rm -f $(REPORTS)
