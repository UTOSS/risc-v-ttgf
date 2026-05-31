# Convert SystemVerilog (.sv) files to Verilog (.v) using sv2v

SV_FILES := $(shell find src/ -follow -name "*.sv" -type f 2>/dev/null | grep -v '/src/src')
INCLUDE_FLAGS := -I src/utoss-risc-v/
DEFINE_FLAGS := -DUTOSS_RISCV_HARDENING
V_FILES := $(SV_FILES:.sv=.sv2v.v)

.PHONY: sv2v tt clean help

sv2v:
	@mkdir -p .sv2v_temp
	@sv2v $(INCLUDE_FLAGS) $(DEFINE_FLAGS) $(SV_FILES) -w .sv2v_temp
	@for svfile in $(SV_FILES); do \
		module_name=$$(basename "$$svfile" .sv); \
		generated_file=$$(find .sv2v_temp -maxdepth 1 -type f -iname "$$module_name.v" | head -n 1); \
		if [ -n "$$generated_file" ]; then \
			mv "$$generated_file" "$$(dirname "$$svfile")/$$module_name.sv2v.v"; \
		fi; \
	done
	@missing=0; \
	for relpath in $$(sed -n 's/^[[:space:]]*-[[:space:]]*"\(.*\.sv2v\.v\)".*/\1/p' info.yaml); do \
		if [ ! -f "src/$$relpath" ]; then \
			echo "ERROR: Expected generated file missing: src/$$relpath" >&2; \
			missing=1; \
		fi; \
	done; \
	test $$missing -eq 0
	@rm -rf .sv2v_temp

tt: sv2v
	./tt/tt_tool.py --create-user-config --gf
	./tt/tt_tool.py --harden --gf

clean:
	@rm -f $(V_FILES)
