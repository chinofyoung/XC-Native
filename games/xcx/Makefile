# Xenoblade Chronicles X: Definitive Edition native runtime. Self-contained: the Horizon host (runtime/), the rewriter
# (third_party/d2r), the NVN-on-Metal layer (third_party/d2r_gfx), the shader translator (prebuilt/) and the scripts are
# this folder's own copies, forked from the original project's games/by3 (the translator's source: tools/totk_xlate and
# the repository's vendor/ryujinx). The runtime is retargeted to Xenoblade Chronicles X (title 0100453019AA8000), update
# 1.0.1 or 2.0.0: VERSION=v101 (the default) or VERSION=v200 (scripts/app_bundle.py VERSIONS, runtime/game_version.h).
# Everything generated goes to the work folder, each version's apart: build/<v>/ (generated headers),
# build/xcx-native-<v>, build/launcher-<v>; the graphics objects, the shader tools and the shader cache are shared.
# This is the developer path; players build with the repository's root build_app.py, which runs these same targets
# (prepare, runtime, shader-tools, launcher, icon) with WORK=<its work folder> and then makes a self-contained app.
# Inputs come from scripts/extract_code.py, scripts/merge_romfs.py and the rewrite (see README.md), then:
#   make prepare   # scripts/prepare_runtime.py: tables, RomFS index, fonts config
#   make runtime   # <work>/build/xcx-native-<v> (default work folder: XCX_build at the repository root)
#   make boot      # run it from the work folder (cwd: extracted/ and rewritten/ are read relative to it);
#                  # TOTK_GPU_ALLOW_SUBMIT=1 for a picture, TOTK_HEADLESS=1 to stop where the game first needs a window
#   make app       # <work>/Xenoblade Chronicles X.app: double-click it (the launcher sets the picture's switches itself);
#                  # a development app that runs the game from the work folder

WORK ?= ../../XCX_build
OUT := $(WORK)/build
PY ?= python3
NATIVE_OPT ?= -O2
VERSION ?= v101
ifeq ($(filter v101 v200,$(VERSION)),)
$(error VERSION must be v101 (1.0.1) or v200 (2.0.0), not "$(VERSION)")
endif
VERSION_FLAGS := -DXCX_GAME_$(subst v,V,$(VERSION))
GEN := $(OUT)/$(VERSION)
BINARY := $(OUT)/xcx-native-$(VERSION)
LAUNCHER := $(OUT)/launcher-$(VERSION)

GFX_SRC := $(wildcard third_party/d2r_gfx/gfx/nvn/*.c third_party/d2r_gfx/gfx/nvn/*.m third_party/d2r_gfx/gfx/nvn/*.S third_party/d2r_gfx/gfx/tex/*.c third_party/d2r_gfx/gfx/tex/*.m)
GFX_OBJECTS := $(patsubst %,$(OUT)/obj/%.o,$(GFX_SRC))
GFX_HEADERS := $(wildcard third_party/d2r_gfx/gfx/nvn/*.h third_party/d2r_gfx/gfx/nvn/include/*.h third_party/d2r_gfx/host/*.h)
GFX_FLAGS := -DGAME_XCX -std=gnu11 -Wno-error -Wno-unused-function -Wno-unused-parameter -fobjc-arc -Ithird_party/d2r_gfx/gfx/nvn/include

RUNTIME_SRC := $(filter-out runtime/frontend_ios.m,$(wildcard runtime/*.c runtime/*.m runtime/*.S))
RUNTIME_HEADERS := $(wildcard runtime/*.h)
GENERATED := $(GEN)/runtime_tables.h $(GEN)/romfs_config.h $(GEN)/shared_fonts_config.h

.PHONY: prepare runtime boot clean
prepare:
	"$(PY)" scripts/prepare_runtime.py --work "$(WORK)" --version $(VERSION)

$(GENERATED):
	@echo "missing $@: run make prepare VERSION=$(VERSION)" && false

$(OUT)/obj/%.o: % $(GFX_HEADERS) Makefile
	@mkdir -p "$(dir $@)"
	xcrun clang $(NATIVE_OPT) -g -Wall -Wextra $(GFX_FLAGS) -c "$<" -o "$@"

$(BINARY): $(RUNTIME_SRC) $(RUNTIME_HEADERS) $(GENERATED) $(GFX_OBJECTS) Makefile
	xcrun clang -std=c11 $(NATIVE_OPT) -g -Wall -Wextra -Werror -Wno-deprecated-declarations $(VERSION_FLAGS) \
	  -Ithird_party/d2r_gfx/gfx/nvn/include -I$(GEN) -I/opt/homebrew/opt/opus/include/opus -I/opt/homebrew/opt/libvpx/include \
	  $(RUNTIME_SRC) $(GFX_OBJECTS) /opt/homebrew/opt/opus/lib/libopus.a /opt/homebrew/opt/libvpx/lib/libvpx.a \
	  -framework Metal -framework MetalFX -framework Foundation -framework QuartzCore -framework ImageIO -framework CoreGraphics \
	  -framework CoreText -framework UniformTypeIdentifiers -fobjc-arc -framework Cocoa -framework CoreVideo -framework CoreFoundation \
	  -framework AudioToolbox -framework GameController -framework CoreHaptics -framework IOKit -o "$@"

runtime: $(BINARY)

# The runtime shader translation the graphics layer starts on first use: <work>/build/shader-service/totk_xlate (the
# repository's prebuilt NativeAOT translator, checked against its SHA-256) and <work>/build/spirv-cross/spirv-cross,
# built like the original project's build_app.py did (same pinned commit, sources and flags as SPIRV-Cross's CMake
# Release build).
SPIRV_CROSS_COMMIT := aa217aeb6c9f0ace7a0ab233b28807edf45eb165
SPIRV_CROSS_SOURCES := main.cpp spirv_cfg.cpp spirv_cpp.cpp spirv_cross.cpp spirv_cross_parsed_ir.cpp spirv_cross_util.cpp \
  spirv_glsl.cpp spirv_hlsl.cpp spirv_msl.cpp spirv_parser.cpp spirv_reflect.cpp
.PHONY: shader-tools
shader-tools: $(OUT)/shader-service/totk_xlate $(OUT)/spirv-cross/spirv-cross
$(OUT)/shader-service/totk_xlate: prebuilt/macos-arm64/totk_xlate prebuilt/macos-arm64/totk_xlate.sha256
	@mkdir -p "$(dir $@)"
	test "$$(shasum -a 256 "$<" | cut -d' ' -f1)" = "$$(cut -d' ' -f1 "prebuilt/macos-arm64/totk_xlate.sha256")"
	cp "$<" "$@" && chmod +x "$@"
$(OUT)/spirv-cross/spirv-cross:
	@mkdir -p "$(WORK)/src" "$(dir $@)obj"
	test -d "$(WORK)/src/SPIRV-Cross" || git clone -q https://github.com/KhronosGroup/SPIRV-Cross.git "$(WORK)/src/SPIRV-Cross"
	git -C "$(WORK)/src/SPIRV-Cross" checkout -q $(SPIRV_CROSS_COMMIT)
	for f in $(SPIRV_CROSS_SOURCES); do xcrun clang++ -O3 -DNDEBUG -std=c++11 -arch arm64 -Wno-deprecated-declarations \
	  -c "$(WORK)/src/SPIRV-Cross/$$f" -o "$(dir $@)obj/$$f.o" & done; wait
	xcrun clang++ -arch arm64 $(addprefix $(dir $@)obj/,$(addsuffix .o,$(SPIRV_CROSS_SOURCES))) -o "$@"

# XCX_LOG: where the boot's stderr goes (the host is loud on purpose; every abort names what is missing).
XCX_LOG ?= $(WORK)/logs/boot.log
boot: runtime
	@mkdir -p "$(dir $(XCX_LOG))"
	cd "$(WORK)" && TOTK_HEADLESS=$${TOTK_HEADLESS-} ./build/xcx-native-$(VERSION) rewritten/$(VERSION) boot 2> "$(abspath $(XCX_LOG))"; echo "exit $$?; log: $(XCX_LOG)"

# The player's mods, made into checked tables: exefs patches (mods/<1.0.1 | 2.0.0>/<name>/exefs/*.pchtxt, for VERSION's
# main build ID) -> <work>/patches,
# RomFS mods (mods/<name>/romfs/...) -> their manifest.tsv (sizes and SHA-256 of the replacements and the originals).
.PHONY: patches mods app
patches:
	"$(PY)" scripts/prepare_patches.py --work "$(WORK)" --version $(VERSION)
mods:
	for d in mods/*/romfs; do [ -d "$$d" ] && "$(PY)" scripts/make_mod_manifest.py "$$d" --romfs "$(WORK)/extracted/$(VERSION)/romfs"; done; true

# The app: a small launcher bundle (settings window with presets, then the game) that runs the game from the work
# folder, which it names in Info.plist (XCXWorkFolder): nothing large is copied. Its icon comes from the game's own
# control data (GAME=<the XCI> KEYS=<prod.keys>), or the app goes without one. The app is built into the work folder,
# never into this source tree. Saves: ~/Library/Application Support/XCNative/XCX/profile, copied from
# <work>/user-data on the first start (app/launcher.m); shader cache: <work>/build/shader-cache, shared with make boot.
# Info.plist and the bundle layout are scripts/app_bundle.py's, shared with the self-contained app of build_app.py.
APP_NAME := Xenoblade Chronicles X.app
APP ?= $(WORK)/$(APP_NAME)
GAME ?=
KEYS ?=
TITLE_KEYS ?=
.PHONY: launcher icon
launcher: $(LAUNCHER)
icon: $(OUT)/AppIcon.icns
# dmsh_chain.h: the shader cache's name, which a self-contained app keeps in the user's Library; totk_shader_contrib.h:
# the share reminder and the contribution file; game_version.h: the version the launcher's --check compares with
# Info.plist; xcx_saves.m: Export / Import Saves (zlib for the zip)
$(LAUNCHER): app/launcher.m app/xcx_saves.m app/xcx_saves.h third_party/d2r_gfx/gfx/nvn/dmsh_chain.h third_party/d2r_gfx/gfx/nvn/totk_shader_contrib.h \
             runtime/game_version.h Makefile
	@mkdir -p "$(dir $@)"
	xcrun clang -std=gnu11 -O2 -Wall -Wextra -Werror -fobjc-arc $(VERSION_FLAGS) -Ithird_party/d2r_gfx/gfx/nvn -Iruntime app/launcher.m app/xcx_saves.m -framework Cocoa -framework UniformTypeIdentifiers -lz -o "$@"
$(OUT)/AppIcon.icns:
	@if [ -n "$(GAME)" ] && [ -n "$(KEYS)" ]; then cd scripts && "$(PY)" extract_app_icon.py "$(GAME)" --keys "$(KEYS)" --title 0100453019aa8000 $(if $(TITLE_KEYS),--title-keys "$(TITLE_KEYS)") --output "$(abspath $@)"; \
	 else echo "no GAME= / KEYS=: the app gets no icon"; fi
app: runtime shader-tools $(LAUNCHER) $(OUT)/AppIcon.icns
	"$(PY)" scripts/app_bundle.py dev --app "$(APP)" --launcher "$(LAUNCHER)" --work "$(WORK)" --icon "$(OUT)/AppIcon.icns" --version $(VERSION)
	codesign --force --sign - "$(APP)"
	@echo "built $(APP) (game data stay in $(abspath $(WORK)))"

# Install the (small) app where Launchpad and Spotlight look: /Applications, or ~/Applications when that is not writable.
INSTALL_DIR ?= $(shell [ -w /Applications ] && echo /Applications || echo $(HOME)/Applications)
.PHONY: install
install: app
	mkdir -p "$(INSTALL_DIR)" && rm -rf "$(INSTALL_DIR)/$(APP_NAME)" && cp -R "$(APP)" "$(INSTALL_DIR)/"
	/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$(INSTALL_DIR)/$(APP_NAME)"
	@echo "installed $(INSTALL_DIR)/$(APP_NAME)"

clean:
	rm -rf "$(OUT)/obj" "$(BINARY)" "$(BINARY).dSYM"
