/* Xenoblade Chronicles X launcher: a settings window with presets, then the game. Forked from Bayonetta 3's launcher.
   The presets are Xenoblade Chronicles X's (stage 5): the game's own 30 fps, no MetalFX upscaling, no frame interpolation,
   the compact HUD: the configuration every stage-4 run was verified with. Bayonetta 3's 60 / 120 fps, fixed-900p,
   improved-LOD and film-grain choices were removed: they named exefs patches that do not exist for this game.
   Two kinds of app (scripts/app_bundle.py):
   - self-contained (the root build_app.py): the game folder is inside the app, Contents/Resources/xcx (the binary, the
     rewritten code, the RomFS index and fonts; the RomFS image is the signed data bundle in Contents/Helpers that
     extracted/<v>/romfs/romfs.bin links to). The app can be moved anywhere. Everything the game writes goes to the
     user's Library, so the signed bundle stays read-only: the shader cache to Application Support/XCNative/XCX/
     shader-cache/rt-<chain> (as Tears of the Kingdom's app), the RomFS check record to .../XCX/app-romfs-record.
   - development (`make app`): a small bundle; the game's data stay in the work folder (XCX_build) named by
     Info.plist's XCXWorkFolder (or XCX_WORK), so nothing large is copied; it runs build/xcx-native-<v>.
   The game version (1.0.1 or 2.0.0) is compiled in (runtime/game_version.h, make VERSION=<v>): <v> is TOTK_GAME_DIR.
   The self-contained mode is used when Contents/Resources/xcx holds the game binary and XCX_WORK is not set.
   Settings are saved at every change (org.xcnative.xcx; the first start takes over org.macnativegames.xcx's, the
   identifier until 2026-10-24) and shown again next time.
   What each setting does in the runtime:
   - Frame rate: 30 (the game's own; the default) or 60 (experimental): the port's 60 fps patch (XCX_PATCHES=60fps,
     runtime/game_patches.c: the game's vsync count 2 -> 1 and its frame time measured; not part of the presets, saved as
     "frame_rate"; XCX_FRAME_RATE=30|60 from the environment wins for one start, for scripted checks). Either way on a 60 Hz
     present base (DM_PRESENT_HZ=60) with the game's present interval 1. The internal resolution is the game's own
     (dynamic, up to 1600x900).
   - Rendering: docked (the default) or handheld (TOTK_OPERATION_MODE=docked|handheld: the game uses its own Switch handheld
     settings, a 1280x720 output and a lower internal resolution, so the GPU renders less; input is the same; not part of the
     presets, saved as "handheld"; TOTK_OPERATION_MODE from the environment wins for one start, for scripted checks).
   - Monitor (XCX_DISPLAY), window or full screen (XCX_FULLSCREEN), window size (TOTK_WINDOW_SIZE), the full-screen
     output resolution (TOTK_DRAWABLE_SCALE relative to the monitor's pixels) and the scaler (MetalFX spatial upscaling of
     the game's picture to the output, TOTK_MFX_UPSCALE / TOTK_MFX_OUTPUT, or plain linear scaling).
   - The RomFS interface mod; the FPS / resolution HUD.
   Player exefs patches (scripts/prepare_patches.py -> <game folder>/patches/<slug>.tsv) have no setting: XCX_PATCHES
   from the environment (open --env XCX_PATCHES=<slug>,<slug> <app>) reaches the runtime (runtime/game_patches.c), with
   60fps added when the frame rate is 60; unset and at 30 fps, none is applied.
   Progress: the player's profile (account, saves, pseudo device id, pipeline list) is in Application Support
   (XCNative/XCX/profile). On the first start without one it is seeded by COPYING <work>/user-data (the profile the
   terminal runs use), so Continue loads the same save; the originals are never moved or changed (development apps
   only: a self-contained app has no work folder). A development app's shader cache stays where the runtime keeps it,
   next to the binary (<work>/build/shader-cache/rt-*), so it and make boot share it.
   Shaders the shared shader list lacks: the game notes them in <data>/shader-list-contribution.txt (TOTK_SHADER_CONTRIB);
   before the game starts the launcher asks, at 50 and then every 500 more, to share the file (contrib_reminder).
   Until 2026-10-24 the data and log folders were MacNativeGames' (Application Support/MacNativeGames/XCX,
   Logs/MacNativeGames): the first start moves them (use_library). */
#import <Cocoa/Cocoa.h>
#include "dmsh_chain.h"      /* DMSH_CHAIN: the shader cache's name (third_party/d2r_gfx/gfx/nvn) */
#include "game_version.h"    /* TOTK_GAME_VERSION, TOTK_GAME_DIR (runtime/) */
#include "totk_shader_contrib.h"   /* the shared shader list contribution and its reminder (third_party/d2r_gfx/gfx/nvn) */
#include <errno.h>
#include <libproc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static BOOL spanish(void) { return [NSLocale.preferredLanguages.firstObject hasPrefix:@"es"]; }
#define T(es, en) (spanish() ? @es : @en)

/* output: 0 = the monitor's native pixels, else the height of a 16:9 output (2160, 1440, 1080, 900). */
typedef struct { const char *name_es, *name_en; int fullscreen, metalfx, output, size; } Preset;
static const Preset presets[] = {   // XCX: no MetalFX (spatial upscaling not yet checked for this game)
    {"Original (30 fps, ventana)", "Original (30 fps, window)", 0, 0, 0, 2},
    {"Original (30 fps, pantalla completa)", "Original (30 fps, full screen)", 1, 0, 0, 2},
};
enum { NPRESETS = sizeof presets / sizeof *presets };
static const int sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}};
static const int outputs[] = {0, 2160, 1440, 1080, 900};

/* The game binary: build/xcx-native inside a self-contained app, build/xcx-native-<v> in a work folder (each version
   has its own there; scripts/app_bundle.py). */
#define APP_BINARY @"build/xcx-native"
#define WORK_BINARY @"build/xcx-native-" TOTK_GAME_DIR
/* The game folder inside a self-contained app, when it holds the game binary (else nil). */
static NSString *bundle_root(void) {
    NSString *root = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"xcx"];
    return [NSFileManager.defaultManager isExecutableFileAtPath:[root stringByAppendingPathComponent:APP_BINARY]] ? root : nil;
}
/* Self-contained unless XCX_WORK names a work folder (a development run of a self-contained app's launcher). */
static BOOL self_contained(void) { const char *e = getenv("XCX_WORK"); return !(e && *e) && bundle_root() != nil; }
/* The game folder: the work folder (XCX_WORK, else Info.plist's XCXWorkFolder) or the one inside the app. */
static NSString *work_folder(void) {
    const char *e = getenv("XCX_WORK");
    if (e && *e) return @(e);
    return bundle_root() ?: [NSBundle.mainBundle objectForInfoDictionaryKey:@"XCXWorkFolder"];
}
static NSString *game_binary(void) { return [work_folder() stringByAppendingPathComponent:self_contained() ? APP_BINARY : WORK_BINARY]; }
/* The user's data and log folders: Application Support/XCNative/XCX and Logs/XCNative, or the MacNativeGames ones they
   were until 2026-10-24 while those could not be moved (use_library, at the start). */
#define DATA_FOLDER @"Library/Application Support/XCNative/XCX"
#define OLD_DATA_FOLDER @"Library/Application Support/MacNativeGames/XCX"
#define LOGS_FOLDER @"Library/Logs/XCNative"
#define OLD_LOGS_FOLDER @"Library/Logs/MacNativeGames"
#define OLD_BUNDLE_ID @"org.macnativegames.xcx"
static NSString *g_data, *g_logs;
static NSString *in_home(NSString *sub) { return [NSHomeDirectory() stringByAppendingPathComponent:sub]; }
static NSString *data_folder(void) { return g_data ?: in_home(DATA_FOLDER); }
static NSString *logs_folder(void) { return g_logs ?: in_home(LOGS_FOLDER); }
/* RomFS mods: <work>/../mods/<name>/romfs with a manifest.tsv (make mods); a self-contained app: <data>/mods. */
static NSString *mods_folder(void) {
    return self_contained() ? [data_folder() stringByAppendingPathComponent:@"mods"]
                            : [[work_folder() stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"mods"];
}
static NSArray<NSString *> *romfs_mods(void) {
    NSMutableArray *out = [NSMutableArray array];
    for (NSString *name in [[NSFileManager.defaultManager contentsOfDirectoryAtPath:mods_folder() error:nil] sortedArrayUsingSelector:@selector(compare:)])
        if ([NSFileManager.defaultManager fileExistsAtPath:[mods_folder() stringByAppendingFormat:@"/%@/romfs/manifest.tsv", name]]) [out addObject:name];
    return out;
}
static NSSize screen_pixels(NSScreen *s) { CGFloat k = s.backingScaleFactor > 0 ? s.backingScaleFactor : 1; return NSMakeSize(round(s.frame.size.width * k), round(s.frame.size.height * k)); }
static NSString *screen_name(NSScreen *s) { return s.localizedName ?: @"?"; }

@interface Launcher : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow *window;
@property NSPopUpButton *preset, *size, *monitor, *output, *mod, *fps;
@property NSSegmentedControl *display, *scaler, *rendering;
@property NSButton *hud, *play; @property NSTextField *note;
@property NSArray<NSString *> *mods; @property BOOL applying, launch;
@end

@implementation Launcher
- (NSTextField *)label:(NSString *)s { NSTextField *l = [NSTextField labelWithString:s]; l.alignment = NSTextAlignmentRight; return l; }
- (NSPopUpButton *)popup:(NSArray<NSString *> *)items { NSPopUpButton *p = [NSPopUpButton new]; [p addItemsWithTitles:items]; p.target = self; p.action = @selector(changed:); return p; }
- (NSSegmentedControl *)segments:(NSArray<NSString *> *)labels {
    return [NSSegmentedControl segmentedControlWithLabels:labels trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
}
- (void)applicationDidFinishLaunching:(NSNotification *)n {
    (void)n;
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    self.preset = [NSPopUpButton new];
    for (int i = 0; i < NPRESETS; i++) [self.preset addItemWithTitle:spanish() ? @(presets[i].name_es) : @(presets[i].name_en)];
    [self.preset addItemWithTitle:T("Personalizado", "Custom")];
    self.preset.target = self; self.preset.action = @selector(presetChanged:);
    self.monitor = [NSPopUpButton new]; self.monitor.target = self; self.monitor.action = @selector(monitorChanged:);
    for (NSScreen *s in NSScreen.screens) {
        NSSize px = screen_pixels(s);
        [self.monitor addItemWithTitle:[NSString stringWithFormat:@"%@ — %.0f × %.0f, %ld Hz", screen_name(s), px.width, px.height, (long)s.maximumFramesPerSecond]];
    }
    self.display = [self segments:@[T("Ventana", "Window"), T("Pantalla completa", "Full screen")]];
    NSMutableArray *sizeTitles = [NSMutableArray array];
    for (unsigned i = 0; i < sizeof sizes / sizeof *sizes; i++) [sizeTitles addObject:[NSString stringWithFormat:@"%d × %d", sizes[i][0], sizes[i][1]]];
    self.size = [self popup:sizeTitles];
    self.output = [NSPopUpButton new]; self.output.target = self; self.output.action = @selector(changed:);
    self.scaler = [self segments:@[T("MetalFX (más nítido)", "MetalFX (sharper)"), T("Normal", "Plain")]];
    self.mod = [self popup:@[T("Ninguno", "None")]]; self.mods = romfs_mods(); [self.mod addItemsWithTitles:self.mods];
    self.fps = [self popup:@[T("30 (original)", "30 (original)"), T("60 (experimental)", "60 (experimental)")]];
    self.rendering = [self segments:@[T("Sobremesa (más nítido)", "Docked (sharper)"), T("Portátil (más rápido)", "Handheld (faster)")]];
    self.hud = [NSButton checkboxWithTitle:T("Mostrar FPS y resolución (tecla 1 lo oculta)", "Show FPS and resolution (key 1 hides it)") target:self action:@selector(changed:)];
    self.note = [NSTextField wrappingLabelWithString:@""]; self.note.textColor = NSColor.secondaryLabelColor; self.note.font = [NSFont systemFontOfSize:11];
    self.play = [NSButton buttonWithTitle:T("Jugar", "Play") target:self action:@selector(start:)]; self.play.keyEquivalent = @"\r";
    NSButton *quit = [NSButton buttonWithTitle:T("Salir", "Quit") target:NSApp action:@selector(terminate:)]; quit.keyEquivalent = @"\033";

    NSGridView *grid = [NSGridView gridViewWithViews:@[
        @[[self label:T("Preset", "Preset")], self.preset],
        @[[self label:T("Imágenes por segundo", "Frame rate")], self.fps],
        @[[self label:T("Renderizado", "Rendering")], self.rendering],
        @[[self label:T("Monitor", "Monitor")], self.monitor],
        @[[self label:T("Pantalla", "Display")], self.display],
        @[[self label:T("Tamaño de la ventana", "Window size")], self.size],
        @[[self label:T("Resolución de salida", "Output resolution")], self.output],
        @[[self label:T("Escalado", "Scaling")], self.scaler],
        @[[self label:T("Mod de interfaz", "Interface mod")], self.mod],
        @[[self label:T("Información", "Info")], self.hud],
    ]];
    grid.rowSpacing = 10; grid.columnSpacing = 12; [grid columnAtIndex:0].xPlacement = NSGridCellPlacementTrailing;
    NSStackView *buttons = [NSStackView stackViewWithViews:@[quit, self.play]];
    NSStackView *stack = [NSStackView stackViewWithViews:@[grid, self.note, buttons]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical; stack.alignment = NSLayoutAttributeTrailing; stack.spacing = 16;
    stack.edgeInsets = NSEdgeInsetsMake(20, 20, 20, 20);
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 680, 480) styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                                backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Xenoblade Chronicles X"; self.window.contentView = stack; self.window.delegate = self;
    [self.note.widthAnchor constraintEqualToConstant:600].active = YES;

    [self loadCommon:d];
    NSInteger p = [d objectForKey:@"preset"] ? [d integerForKey:@"preset"] : 0;
    if (p >= 0 && p < NPRESETS) [self applyPreset:(int)p]; else { [self.preset selectItemAtIndex:NPRESETS]; [self load:d]; }
    [self refresh];
    [self.window center]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    /* XCX_PLAY=1 (open --env XCX_PLAY=1 <app>): Play at once with the saved settings, for scripted checks of the app as
       built (the settings window needs a click otherwise). */
    const char *play = getenv("XCX_PLAY");
    if (play && !strcmp(play, "1") && self.play.enabled) dispatch_async(dispatch_get_main_queue(), ^{ [self start:nil]; });
}
- (NSScreen *)chosenScreen { NSInteger i = self.monitor.indexOfSelectedItem; NSArray *all = NSScreen.screens; return i >= 0 && i < (NSInteger)all.count ? all[i] : NSScreen.mainScreen; }
/* The output resolutions this monitor can show: native first, then the 16:9 ones that fit. */
- (void)fillOutputs:(int)want {
    [self.output removeAllItems];
    NSSize px = screen_pixels(self.chosenScreen); int pick = 0, k = 0;
    for (unsigned i = 0; i < sizeof outputs / sizeof *outputs; i++) {
        int h = outputs[i];
        if (h && h > px.height) continue;
        [self.output addItemWithTitle:h ? [NSString stringWithFormat:@"%d × %d", h * 16 / 9, h] : [NSString stringWithFormat:T("Nativa del monitor (%.0f × %.0f)", "The monitor's native (%.0f × %.0f)"), px.width, px.height]];
        self.output.lastItem.tag = h; if (h == want) pick = k; k++;
    }
    [self.output selectItemAtIndex:pick];
}
- (void)loadCommon:(NSUserDefaults *)d {   // not part of presets
    NSString *m = [d stringForKey:@"monitor"]; NSArray *all = NSScreen.screens; NSUInteger mi = [all indexOfObject:NSScreen.mainScreen];
    if (mi == NSNotFound) mi = 0;
    for (NSUInteger i = 0; i < all.count; i++) if (m && [screen_name(all[i]) isEqualToString:m]) mi = i;
    [self.monitor selectItemAtIndex:(NSInteger)mi];
    self.hud.state = [d objectForKey:@"hud"] ? [d boolForKey:@"hud"] : YES;
    [self.fps selectItemAtIndex:[d integerForKey:@"frame_rate"] == 60 ? 1 : 0];
    self.rendering.selectedSegment = [d boolForKey:@"handheld"];
    NSString *mod = [d stringForKey:@"mod"]; NSUInteger i = mod ? [self.mods indexOfObject:mod] : NSNotFound;
    [self.mod selectItemAtIndex:i == NSNotFound ? 0 : (NSInteger)i + 1];
}
/* Keys of removed settings (fps, fixed900, lod, nograin) that older versions saved are no longer read. */
- (void)load:(NSUserDefaults *)d {
    self.display.selectedSegment = [d boolForKey:@"fullscreen"];
    NSInteger s = [d objectForKey:@"size"] ? [d integerForKey:@"size"] : 2; [self.size selectItemAtIndex:s >= 0 && s < 4 ? s : 2];
    self.scaler.selectedSegment = [d boolForKey:@"metalfx"] ? 0 : 1;   // XCX: off unless chosen
    [self fillOutputs:(int)[d integerForKey:@"output"]];
}
- (void)applyPreset:(int)i {
    const Preset *p = &presets[i]; self.applying = YES;
    [self.preset selectItemAtIndex:i]; self.display.selectedSegment = p->fullscreen; [self.size selectItemAtIndex:p->size];
    self.scaler.selectedSegment = p->metalfx ? 0 : 1; [self fillOutputs:p->output]; self.applying = NO;
}
/* Every change is saved at once (and written to disk), so the next start shows the same choices. */
- (void)presetChanged:(id)sender { (void)sender; NSInteger i = self.preset.indexOfSelectedItem; if (i < NPRESETS) [self applyPreset:(int)i]; [self refresh]; [self save]; }
- (void)monitorChanged:(id)sender { (void)sender; [self fillOutputs:(int)self.output.selectedItem.tag]; [self refresh]; [self save]; }
- (void)changed:(id)sender {
    if (!self.applying && sender != self.hud && sender != self.mod && sender != self.fps && sender != self.rendering) [self.preset selectItemAtIndex:NPRESETS];
    [self refresh]; [self save];
}
- (void)refresh {
    BOOL full = self.display.selectedSegment == 1;
    self.size.enabled = !full; self.output.enabled = full;
    NSMutableString *s = [NSMutableString string];
    self.play.enabled = YES;
    if (!work_folder() || ![NSFileManager.defaultManager isExecutableFileAtPath:game_binary()]) {
        if (work_folder()) [s appendFormat:T("No encuentro el juego en %@.", "The game is not in %@."), work_folder()];
        else [s appendString:T("Esta app no contiene el juego: vuelve a crearla con build_app.py.", "This app does not hold the game: build it again with build_app.py.")];
        self.play.enabled = NO;
    }
    if (self.fps.indexOfSelectedItem == 1) {
        if (s.length) [s appendString:@" "];
        [s appendString:T("60 imágenes por segundo es experimental: el juego va a la velocidad correcta también por debajo de 60, pero algunos efectos y animaciones pueden ir algo lentos entonces. En un Mac lento la GPU no llega a 60.",
                          "60 fps is experimental: the game keeps its speed below 60 too, but some effects and animations can run a little slow then. A slower Mac's GPU does not reach 60.")];
    }
    self.note.stringValue = s; self.note.hidden = !s.length;
}
- (void)save {
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    [d setInteger:self.preset.indexOfSelectedItem forKey:@"preset"];
    [d setBool:self.display.selectedSegment == 1 forKey:@"fullscreen"]; [d setInteger:self.size.indexOfSelectedItem forKey:@"size"];
    [d setInteger:self.output.selectedItem.tag forKey:@"output"]; [d setBool:self.scaler.selectedSegment == 0 forKey:@"metalfx"];
    [d setObject:screen_name(self.chosenScreen) forKey:@"monitor"];
    [d setBool:self.hud.state forKey:@"hud"];
    [d setInteger:self.fps.indexOfSelectedItem == 1 ? 60 : 30 forKey:@"frame_rate"];
    [d setBool:self.rendering.selectedSegment == 1 forKey:@"handheld"];
    if (self.mod.indexOfSelectedItem > 0) [d setObject:self.mods[self.mod.indexOfSelectedItem - 1] forKey:@"mod"]; else [d removeObjectForKey:@"mod"];
    CFPreferencesAppSynchronize(kCFPreferencesCurrentApplication);   // the launcher then replaces itself with the game (exec)
}
- (void)start:(id)sender { (void)sender; [self save]; self.launch = YES; [NSApp stop:nil]; [self.window orderOut:nil];
    NSEvent *e = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0 context:nil subtype:0 data1:0 data2:0];
    [NSApp postEvent:e atStart:YES]; }
- (void)windowWillClose:(NSNotification *)n { (void)n; if (!self.launch) { [self save]; [NSApp terminate:nil]; } }
@end

static void fail(NSString *s) {
    NSAlert *a = [NSAlert new]; a.messageText = T("Xenoblade Chronicles X no pudo arrancar", "Xenoblade Chronicles X could not start"); a.informativeText = s; [a runModal];
}
static BOOL make_dir(NSString *p) { return [NSFileManager.defaultManager createDirectoryAtPath:p withIntermediateDirectories:YES attributes:nil error:nil]; }
/* The folders moved from MacNativeGames to XCNative on 2026-10-24 (build_app.py does the same, scripts/app_bundle.py
   migrate_library): when only the old one exists it is renamed to the new one, once (the same volume: nothing is copied).
   Both there: the new one is used and the old one left as it is; nothing is merged or replaced. A move that fails, or
   a game still running (it writes its saves by the path it started with), keeps the old one in use for this start.
   Nothing is deleted. What happened is written to the log once it is open (library_notes). */
static NSMutableArray<NSString *> *library_notes;
static BOOL game_running(void) {
    int n = proc_listallpids(NULL, 0);
    if (n <= 0) return NO;
    int room = n + 64; pid_t *pids = calloc((size_t)room, sizeof *pids);
    if (!pids) return NO;
    n = proc_listallpids(pids, room * (int)sizeof *pids);
    BOOL found = NO; char name[2 * MAXCOMLEN + 1];
    for (int i = 0; i < n && !found; i++)
        if (pids[i] != getpid() && proc_name(pids[i], name, sizeof name) > 0 && !strncmp(name, "xcx-native", 10)) found = YES;
    free(pids);
    return found;
}
static NSString *move_folder(NSString *new, NSString *old) {
    NSFileManager *fm = NSFileManager.defaultManager;
    if ([fm fileExistsAtPath:new]) {
        if ([fm fileExistsAtPath:old]) [library_notes addObject:[NSString stringWithFormat:@"%@ left in place: %@ exists and is used", old, new]];
        return new;
    }
    if (![fm fileExistsAtPath:old]) return new;
    if (game_running()) {
        [library_notes addObject:[NSString stringWithFormat:@"%@ not moved to %@ while the game runs; using %@ for now", old, new, old]];
        return old;
    }
    const char *why = !make_dir(new.stringByDeletingLastPathComponent) ? "its parent folder cannot be made"
                    : rename(old.fileSystemRepresentation, new.fileSystemRepresentation) ? strerror(errno) : NULL;
    if (why) {
        if ([fm fileExistsAtPath:new] && ![fm fileExistsAtPath:old]) {   // moved meanwhile by build_app.py or another start
            [library_notes addObject:[NSString stringWithFormat:@"%@ was moved to %@ meanwhile; using it", old, new]];
            return new;
        }
        [library_notes addObject:[NSString stringWithFormat:@"could not move %@ to %@ (%s); using %@ for now", old, new, why, old]];
        return old;
    }
    [library_notes addObject:[NSString stringWithFormat:@"moved %@ to %@", old, new]];
    return new;
}
static void use_library(void) {
    if (!library_notes) library_notes = [NSMutableArray array];
    g_data = move_folder(in_home(DATA_FOLDER), in_home(OLD_DATA_FOLDER));
    g_logs = move_folder(in_home(LOGS_FOLDER), in_home(OLD_LOGS_FOLDER));
    /* The settings window's choices were saved under the old identifier: taken over while the new one has none. */
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    NSString *mine = NSBundle.mainBundle.bundleIdentifier;   // nil: a launcher started outside an app
    NSDictionary *old = [d persistentDomainForName:OLD_BUNDLE_ID];
    if (mine && ![mine isEqualToString:OLD_BUNDLE_ID] && old.count && ![d persistentDomainForName:mine].count) {
        [d setPersistentDomain:old forName:mine];
        [library_notes addObject:[NSString stringWithFormat:@"settings taken over from %@", OLD_BUNDLE_ID]];
    }
}
/* First start: seed the app's profile from the work folder's (user-data: the profile the terminal runs made) by copying,
   so the app continues the same game. Only when the app has no account yet; nothing is ever overwritten, and the
   originals are left as they are. temp/ and cache/ are the runtime's scratch and are not copied. */
static void seed_profile(NSString *work, NSString *profile) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *from = [work stringByAppendingPathComponent:@"user-data"];
    if ([fm fileExistsAtPath:[profile stringByAppendingPathComponent:@"account.uid"]] ||
        ![fm fileExistsAtPath:[from stringByAppendingPathComponent:@"account.uid"]]) return;
    for (NSString *name in @[@"account.uid", @"pseudo-device.id", @"pso_user.tsv", @"save"]) {
        NSString *src = [from stringByAppendingPathComponent:name], *dst = [profile stringByAppendingPathComponent:name];
        if (![fm fileExistsAtPath:src] || [fm fileExistsAtPath:dst]) continue;
        NSError *err = nil;
        if ([fm copyItemAtPath:src toPath:dst error:&err]) fprintf(stderr, "[launcher] profile: copied %s from %s\n", name.UTF8String, from.UTF8String);
        else fprintf(stderr, "[launcher] profile: copying %s failed: %s\n", name.UTF8String, err.localizedDescription.UTF8String);
    }
}

/* The shaders this Mac's game met that the shared shader list does not have yet (totk_shader_contrib.h), before the game
   starts: first at TOTK_CONTRIB_FIRST rows, then every TOTK_CONTRIB_STEP more, ask the player to share the file. Share
   opens the shader-list issue form and shows the file in Finder to attach; Not now waits for the next threshold; Never
   stops the reminders (the game still notes the shaders). What happened, for the log. */
static const char *contrib_reminder(NSString *path) {
    NSUInteger rows = totk_contrib_due(path);
    if (!rows) return "not due";
    totk_contrib_reminded(path, rows);   // Not now (and Share): the next reminder TOTK_CONTRIB_STEP rows later
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *alert = [NSAlert new];
    alert.messageText = [NSString stringWithFormat:T("Encontraste %lu shaders nuevos. Si los compartes, la próxima app que cada jugador cree dibujará estas partes del juego. ¿Compartir ahora?",
                                                     TOTK_CONTRIB_PROMPT), (unsigned long)rows];
    [alert addButtonWithTitle:T("Compartir", TOTK_CONTRIB_SHARE)];
    [alert addButtonWithTitle:T("Ahora no", TOTK_CONTRIB_NOT_NOW)];
    [alert addButtonWithTitle:T("Nunca", TOTK_CONTRIB_NEVER)];
    NSModalResponse choice = [alert runModal];
    if (choice == NSAlertThirdButtonReturn) { totk_contrib_never(path); return "never"; }
    if (choice != NSAlertFirstButtonReturn) return "not now";
    [NSWorkspace.sharedWorkspace openURL:totk_contrib_issue_url(rows, @TOTK_GAME_VERSION, @"Mac")];
    [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:path]]];
    return "share";
}

int main(int argc, char **argv) {
    @autoreleasepool {
        /* --check (build_app.py, once after packaging): only look that the game is in the app and of the version
           Info.plist declares, then exit. macOS scans a new app the first time it runs (long for a 14 GB bundle, with
           nothing on screen); doing it during the build makes the player's first start immediate. */
        if (argc > 1 && !strcmp(argv[1], "--check")) {
            NSString *declared = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"];
            NSString *folder = [NSBundle.mainBundle objectForInfoDictionaryKey:@"XCXGameVersion"];   // absent in apps built before 2.0.0
            int ok = bundle_root() != nil && [declared isEqualToString:@TOTK_GAME_VERSION] && (!folder || [folder isEqualToString:@TOTK_GAME_DIR]);
            printf("%s: game version %s (%s)\n", ok ? "ok" : "missing game binary or version mismatch", TOTK_GAME_VERSION, TOTK_GAME_DIR);
            return ok ? 0 : 1;
        }
        use_library();   // before anything reads the data folder (the settings window lists its mods)
        [NSApplication sharedApplication]; NSApp.activationPolicy = NSApplicationActivationPolicyRegular;
        Launcher *l = [Launcher new]; NSApp.delegate = l;
        [NSApp run];
        if (!l.launch) return 0;
        use_library();   // again: a build (build_app.py) may have moved the folders while the settings window was open
        NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
        NSString *work = work_folder();
        BOOL bundled = self_contained();
        NSString *data = data_folder();
        NSString *logs = logs_folder();
        NSString *profile = [data stringByAppendingPathComponent:@"profile"], *slot = [data stringByAppendingPathComponent:@"game-slot"];
        /* A self-contained app keeps what the game writes out of its signed bundle (Tears of the Kingdom's app does the
           same): the shader cache in the user's Library, and its own RomFS check record (the record names the image's
           file identity, and the app's image is another file than a work folder's, so the two kinds of app do not
           replace each other's record and verify 14 GB again in turn). XC_SHADER_CACHE (or the older TOTK_SHADER_CACHE) from the
           environment wins. */
        const char *cache_env = getenv("XC_SHADER_CACHE");
        if (!cache_env || !*cache_env) cache_env = getenv("TOTK_SHADER_CACHE");
        NSString *cache = cache_env && *cache_env ? @(cache_env) : [data stringByAppendingFormat:@"/shader-cache/rt-%s", DMSH_CHAIN];
        NSString *record = bundled ? [data stringByAppendingPathComponent:@"app-romfs-record"] : data;
        if (!make_dir(profile) || !make_dir(slot) || !make_dir(logs) || !make_dir(record) || (bundled && !make_dir(cache))) {
            fail([NSString stringWithFormat:@"%@", data]); return 1;
        }
        if (chdir(work.fileSystemRepresentation)) { fail(work); return 1; }   // the runtime reads extracted/ and rewritten/ relative to it

        /* Frame rate 60: the port's 60 fps patch, added to the player's own XCX_PATCHES (see the comment at the top). */
        const char *fr = getenv("XCX_FRAME_RATE");
        BOOL fps60 = fr && *fr ? atoi(fr) == 60 : [d integerForKey:@"frame_rate"] == 60;
        if (fps60) {
            const char *had = getenv("XCX_PATCHES");
            NSString *list = had && *had ? @(had) : @"";
            if (![[list componentsSeparatedByString:@","] containsObject:@"60fps"]) list = list.length ? [list stringByAppendingString:@",60fps"] : @"60fps";
            setenv("XCX_PATCHES", list.UTF8String, 1);
        }
        const char *om = getenv("TOTK_OPERATION_MODE");   // handheld: the game's own handheld settings (see the comment at the top)
        if (!(om && *om)) setenv("TOTK_OPERATION_MODE", [d boolForKey:@"handheld"] ? "handheld" : "docked", 1);
        setenv("DM_PRESENT_HZ", "60", 1);   // the present base at both frame rates: the game presents with interval 1, its own cap paces it

        NSArray<NSScreen *> *all = NSScreen.screens; NSUInteger mi = [all indexOfObject:NSScreen.mainScreen];
        if (mi == NSNotFound) mi = 0;
        for (NSUInteger i = 0; i < all.count; i++) if ([screen_name(all[i]) isEqualToString:[d stringForKey:@"monitor"]]) mi = i;
        setenv("XCX_DISPLAY", [NSString stringWithFormat:@"%lu", (unsigned long)mi].UTF8String, 1);
        BOOL full = [d boolForKey:@"fullscreen"];
        if (full) {
            setenv("XCX_FULLSCREEN", "1", 1);
            int h = (int)[d integerForKey:@"output"]; NSSize px = screen_pixels(all.count ? all[mi] : NSScreen.mainScreen);
            if (h > 0 && h < px.height) setenv("TOTK_DRAWABLE_SCALE", [NSString stringWithFormat:@"%.4f", h / px.height].UTF8String, 1);
        }
        NSInteger s = [d integerForKey:@"size"]; if (s < 0 || s > 3) s = 2;
        setenv("TOTK_WINDOW_SIZE", [NSString stringWithFormat:@"%dx%d", sizes[s][0], sizes[s][1]].UTF8String, 1);
        if ([d boolForKey:@"metalfx"]) { setenv("TOTK_MFX_UPSCALE", "1", 1); setenv("TOTK_MFX_OUTPUT", "1", 1); }
        if ([d objectForKey:@"hud"] && ![d boolForKey:@"hud"]) setenv("TOTK_FPS_OVERLAY", "0", 1); else setenv("XCX_HUD_RENDER", "1", 1);
        unsetenv("TOTK_HUD");   // the compact HUD (corner panel), never TOTK_HUD=corners
        unsetenv("TOTK_MFX");   // MetalFX frame interpolation off at start (stage 4: a net loss on an M1); key 2 still toggles it
        NSString *mod = [d stringForKey:@"mod"];
        if (mod && [romfs_mods() containsObject:mod]) setenv("TOTK_ROMFS_MODS", [mods_folder() stringByAppendingFormat:@"/%@/romfs", mod].fileSystemRepresentation, 1);
        else setenv("TOTK_ROMFS_MODS", "0", 1);

        setenv("TOTK_PROFILE_DIR", profile.fileSystemRepresentation, 1);
        setenv("TOTK_GAME_SLOT_DIR", slot.fileSystemRepresentation, 1);
        setenv("TOTK_ROMFS_PROOF_DIR", record.fileSystemRepresentation, 1);
        if (bundled) {
            setenv("TOTK_SHADER_CACHE", cache.fileSystemRepresentation, 1);
            setenv("TOTK_SHARED_FONTS", "extracted/firmware/shared-fonts", 1);   // the fonts inside the app (runtime/shared_font.c)
        }
        NSString *preferred = NSLocale.preferredLanguages.firstObject; if (preferred) setenv("TOTK_LOCALE", preferred.UTF8String, 1);
        setenv("TOTK_GPU_ALLOW_SUBMIT", "1", 1); setenv("TOTK_GPU_WIDEN", "1", 1); setenv("TOTK_GPU_BLOCKRT", "1", 1);
        setenv("TOTK_GPU_MIDCLEAR", "1", 1);
        unsetenv("TOTK_GPU_BUDGET_MB");   // XCX: the runtime's default budget (40% of memory), as in every stage-4 run (Bayonetta 3's app sets 5000)
        setenv("DM_PRESENT_LINK_FALLBACK", "1", 1);   // keep presenting when macOS pauses the display link for a window it thinks covered
        setenv("TOTK_SLOT_OWNER", "user", 0); setenv("TOTK_SLOT_PURPOSE", "player", 0);   // a scripted check may name itself (open --env)
        unsetenv("TOTK_HEADLESS");
        /* The shaders the shared list lacks are noted here (totk_shader_contrib.h); TOTK_SHADER_CONTRIB from the
           environment wins. */
        const char *contrib_env = getenv("TOTK_SHADER_CONTRIB");
        NSString *contrib = contrib_env && *contrib_env ? @(contrib_env) : [data stringByAppendingPathComponent:@"shader-list-contribution.txt"];
        setenv("TOTK_SHADER_CONTRIB", contrib.fileSystemRepresentation, 1);
        const char *reminder = contrib_reminder(contrib);
        { NSString *cmds = [data stringByAppendingPathComponent:@"input.txt"]; FILE *cf = fopen(cmds.fileSystemRepresentation, "w"); if (cf) fclose(cf);
          setenv("TOTK_INPUT_FILE", cmds.fileSystemRepresentation, 1); }   // echo "shot ~/Desktop/shot.png" >> it

        NSString *log = [logs stringByAppendingPathComponent:@"xcx.log"], *prev = [logs stringByAppendingPathComponent:@"xcx.previous.log"];
        [NSFileManager.defaultManager removeItemAtPath:prev error:nil]; [NSFileManager.defaultManager moveItemAtPath:log toPath:prev error:nil];
        FILE *lf = fopen(log.fileSystemRepresentation, "w"); if (lf) { dup2(fileno(lf), STDOUT_FILENO); dup2(fileno(lf), STDERR_FILENO); fclose(lf); }
        for (NSString *note in library_notes) fprintf(stderr, "[launcher] library: %s\n", note.UTF8String);
        if (!bundled) seed_profile(work, profile);   // after the log is open, so the copy is recorded in it
        { NSString *image = [work stringByAppendingPathComponent:@"extracted/" TOTK_GAME_DIR "/romfs/romfs.bin"];
          fprintf(stderr, "[launcher] %s: game folder %s, RomFS image %s, shader cache %s\n",
                  bundled ? "self-contained app (game data inside the app)" : "development app (game data in the work folder)",
                  work.UTF8String, image.stringByResolvingSymlinksInPath.UTF8String,
                  bundled ? cache.UTF8String : "next to the game binary (build/shader-cache)"); }
        fprintf(stderr, "[launcher] game version %s (%s)\n", TOTK_GAME_VERSION, TOTK_GAME_DIR);
        fprintf(stderr, "[launcher] frame rate %d (%s)\n", fps60 ? 60 : 30, fr && *fr ? "XCX_FRAME_RATE" : "setting");
        fprintf(stderr, "[launcher] operation mode %s (%s)\n", getenv("TOTK_OPERATION_MODE"), om && *om ? "TOTK_OPERATION_MODE" : "setting");
        fprintf(stderr, "[launcher] shader list contribution %s (%lu rows, reminder: %s)\n", contrib.UTF8String,
                (unsigned long)totk_contrib_read(contrib).count, reminder);
        fprintf(stderr, "[launcher] work %s, patches %s, present %s Hz, display %s, fullscreen %s, window %s, drawable scale %s, MetalFX %s, mod %s\n",
                work.UTF8String, getenv("XCX_PATCHES") ?: "none", getenv("DM_PRESENT_HZ"), getenv("XCX_DISPLAY"), full ? "yes" : "no", getenv("TOTK_WINDOW_SIZE"),
                getenv("TOTK_DRAWABLE_SCALE") ?: "1", getenv("TOTK_MFX_OUTPUT") ? "on" : "off", getenv("TOTK_ROMFS_MODS"));
        NSString *binary = game_binary();
        char *const args[] = {(char *)binary.fileSystemRepresentation, "rewritten/" TOTK_GAME_DIR, "boot", NULL};
        execv(args[0], args);
        fprintf(stderr, "[launcher] execv failed: %s\n", strerror(errno));
        fail([NSString stringWithFormat:T("No se pudo iniciar el juego. Mira %@.", "Starting the game failed. See %@."), log]);
        return 1;
    }
}
