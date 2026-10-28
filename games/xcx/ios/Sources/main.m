/* The iPhone / iPad app of the Xenoblade Chronicles X port: restored from the original project's games/totk/ios/Sources/
   main.m and adapted for XCX (names, the game data layout of games/xcx, no shared shader list). UIKit owns the window; the
   game runs on its own thread through the loader's main (runtime/loader.c, built with -Dmain=totk_host_main) and draws
   into the view's Metal layer (runtime/frontend_ios.m). EXPERIMENTAL: an iPhone or iPad cannot translate shaders at run
   time, and this port has no up-front shader translation yet, so a draw whose shader the app does not carry is skipped. */
#import <UIKit/UIKit.h>
#import <AVFAudio/AVFAudio.h>
#import <QuartzCore/CAMetalLayer.h>
#import <GameController/GameController.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <math.h>
#include "runtime.h"
#include "dmsh_chain.h"
#include "romfs_config.h"   // ROMFS_IMAGE_SIZE: the build's image (generated, <work>/build/<v>)
#include "game_version.h"   // TOTK_GAME_DIR (XCX_VERSION_FLAGS: -DXCX_GAME_V101 / V200)
#import "touch_pad.h"
#import "xcx_saves.h"       // save export / import, shared with the Mac launcher (app/xcx_saves.h)

int totk_host_main(int argc, char **argv);
void runtime_ios_attach_layer(CAMetalLayer *layer, UIView *host);
/* The original project's runtime restarts its audio output after an interruption; this runtime has no such call yet
   (runtime/audio_mixer.c). This weak stand-in only says so; a runtime that defines it takes its place at link time. */
__attribute__((weak)) void runtime_audio_output_restart(int recreate) {
    fprintf(stderr,"[xcx-audio] this runtime cannot restart its audio output (recreate=%d); sound may stay off until the game is opened again\n",recreate);
}
static char *host_argv[3];
static NSString *g_no_game_data;   // set when there is no RomFS image to play from (didFinishLaunching)
static BOOL g_skip_start_screen;   // a test launch from the Mac: straight into the game (didFinishLaunching)
static NSString *g_skip_reason;    // the variable that made it skip (logged once log.txt is open)
static NSString *g_profile;        // TOTK_PROFILE_DIR: Documents/save (didFinishLaunching)
static void *run_host(void *unused) { (void)unused; return (void *)(intptr_t)totk_host_main(3, host_argv); }
/* The desktop keyboard-overlay shortcut has no counterpart on iOS. */
void runtime_shortcut_help_toggle(void) {}

@interface XCXMetalView : UIView @end
@implementation XCXMetalView
+ (Class)layerClass { return CAMetalLayer.class; }
@end

@interface XCXGameController : UIViewController @property(nonatomic,strong) XCXMetalView *gameView; @end
@implementation XCXGameController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    self.gameView = [[XCXMetalView alloc] initWithFrame:self.view.bounds];
    self.gameView.autoresizingMask = UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:self.gameView];
    runtime_ios_attach_layer((CAMetalLayer *)self.gameView.layer, self.gameView);
    XCXTouchPad *pad=[[XCXTouchPad alloc] initWithFrame:self.view.bounds];pad.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;[self.view addSubview:pad];
}
- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    static BOOL started; if (started) return; started = YES;
    if (g_no_game_data) {
        UILabel *say = [[UILabel alloc] initWithFrame:CGRectInset(self.view.bounds, 40, 40)];
        say.autoresizingMask = UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
        say.text = g_no_game_data; say.textColor = UIColor.whiteColor; say.numberOfLines = 0; say.textAlignment = NSTextAlignmentCenter;
        [self.view addSubview:say];
        return;
    }
    /* Playback category: plays with the ring / silent switch off and routes to the speaker. Without an active session the
       game's CoreAudio output stays on a null sink; activating it in didFinishLaunching blocked the main thread before the
       log file was opened (the original project's findings). Interruptions: audio_observe. */
    AVAudioSession *audio = AVAudioSession.sharedInstance;
    NSError *catErr = nil, *actErr = nil;
    [audio setCategory:AVAudioSessionCategoryPlayback mode:AVAudioSessionModeDefault options:0 error:&catErr];
    BOOL activated = [audio setActive:YES error:&actErr];
    fprintf(stderr, "[xcx-audio] audio session category=%s active=%d route=%s err=%s%s\n",
            audio.category.UTF8String ?: "?", (int)activated, audio.currentRoute.outputs.firstObject.portType.UTF8String ?: "?",
            catErr ? catErr.localizedDescription.UTF8String : "none", actErr ? actErr.localizedDescription.UTF8String : "");
    pthread_attr_t attr; pthread_attr_init(&attr); pthread_attr_setstacksize(&attr, 64u << 20);
    pthread_t thread; pthread_create(&thread, &attr, run_host, NULL);
    pthread_detach(thread); pthread_attr_destroy(&attr);
}
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
@end

/* The start screen: Play, Export Saves, Import Saves (as the Mac launcher's Saves row, app/launcher.m). The game runs in
   this process and cannot be stopped and started again, so the saves are only exported or replaced here, before Play
   starts it; after Play the screen is gone. Export writes the zip (xcx_saves_export) to the temporary folder and hands it
   to the share sheet (Save to Files, AirDrop, ...); Import takes a zip from the Files picker (a copy), shows what it
   holds (xcx_saves_inspect) and on Import backs Documents/save up to Documents/save-<version>-backup-<date> (in the Files
   app) and replaces the saves (xcx_saves_import). A test launch skips the screen (g_skip_start_screen). A controller's
   A button presses Play. */
@interface XCXStartController : UIViewController <UIDocumentPickerDelegate>
@property(nonatomic,strong) UIButton *play, *exportSaves, *importSaves;
@property(nonatomic,strong) UILabel *note;
@property(nonatomic,strong) UIActivityIndicatorView *spinner;
@end
@implementation XCXStartController
static NSString *app_name(void) { return [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleDisplayName"] ?: @"Xenoblade Chronicles X"; }
- (UIButton *)button:(NSString *)title primary:(BOOL)primary action:(SEL)action {
    UIButtonConfiguration *c = primary ? UIButtonConfiguration.filledButtonConfiguration : UIButtonConfiguration.grayButtonConfiguration;
    c.title = title; c.cornerStyle = UIButtonConfigurationCornerStyleLarge;
    c.titleTextAttributesTransformer = ^NSDictionary *(NSDictionary *in) {
        NSMutableDictionary *out = in.mutableCopy; out[NSFontAttributeName] = [UIFont systemFontOfSize:primary ? 26 : 17 weight:primary ? UIFontWeightBold : UIFontWeightSemibold]; return out; };
    UIButton *b = [UIButton buttonWithConfiguration:c primaryAction:nil];
    [b addTarget:self action:action forControlEvents:UIControlEventPrimaryActionTriggered];
    b.translatesAutoresizingMaskIntoConstraints = NO;
    return b;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    self.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    UILabel *title = [UILabel new]; title.text = app_name(); title.textColor = UIColor.whiteColor;
    title.font = [UIFont systemFontOfSize:28 weight:UIFontWeightBold]; title.textAlignment = NSTextAlignmentCenter; title.adjustsFontSizeToFitWidth = YES;
    self.play = [self button:@"Play" primary:YES action:@selector(play:)];
    self.exportSaves = [self button:@"Export Saves" primary:NO action:@selector(exportSaves:)];
    self.importSaves = [self button:@"Import Saves" primary:NO action:@selector(importSaves:)];
    UIStackView *saves = [[UIStackView alloc] initWithArrangedSubviews:@[self.exportSaves, self.importSaves]];
    saves.spacing = 16; saves.distribution = UIStackViewDistributionFillEqually;
    self.note = [UILabel new]; self.note.textColor = UIColor.lightGrayColor; self.note.font = [UIFont systemFontOfSize:14];
    self.note.numberOfLines = 0; self.note.textAlignment = NSTextAlignmentCenter;
    self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];
    self.spinner.color = UIColor.whiteColor; self.spinner.hidesWhenStopped = YES;
    UIStackView *all = [[UIStackView alloc] initWithArrangedSubviews:@[title, self.play, saves, self.spinner, self.note]];
    all.axis = UILayoutConstraintAxisVertical; all.alignment = UIStackViewAlignmentCenter; all.spacing = 18;
    [all setCustomSpacing:28 afterView:title];
    all.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:all];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [all.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor], [all.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [all.widthAnchor constraintLessThanOrEqualToAnchor:safe.widthAnchor constant:-32],
        [all.topAnchor constraintGreaterThanOrEqualToAnchor:safe.topAnchor constant:8],
        [title.widthAnchor constraintLessThanOrEqualToAnchor:all.widthAnchor],
        [self.play.widthAnchor constraintEqualToConstant:336], [self.play.heightAnchor constraintEqualToConstant:64],
        [saves.widthAnchor constraintEqualToAnchor:self.play.widthAnchor], [self.exportSaves.heightAnchor constraintEqualToConstant:44],
        [self.importSaves.heightAnchor constraintEqualToAnchor:self.exportSaves.heightAnchor],
        [self.note.widthAnchor constraintLessThanOrEqualToConstant:560], [self.note.widthAnchor constraintLessThanOrEqualToAnchor:all.widthAnchor],
    ]];
    for (GCController *c in GCController.controllers) [self watchController:c];
    [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(controllerConnected:) name:GCControllerDidConnectNotification object:nil];
    [self refresh];
}
- (void)dealloc { [NSNotificationCenter.defaultCenter removeObserver:self]; }
- (void)controllerConnected:(NSNotification *)n { [self watchController:n.object]; }
- (void)watchController:(GCController *)c {
    __weak XCXStartController *weak = self;
    c.extendedGamepad.buttonA.pressedChangedHandler = ^(GCControllerButtonInput *b, float v, BOOL pressed) {
        (void)b; (void)v;
        XCXStartController *me = weak;
        if (pressed && me && me.play.enabled && !me.presentedViewController && me.view.window) [me play:nil];
    };
}
- (void)refresh {
    BOOL busy = self.spinner.isAnimating;
    NSUInteger saves = xcx_saves_list(g_profile).count;
    self.play.enabled = !g_no_game_data && !busy;
    self.exportSaves.enabled = saves > 0 && !busy;
    self.importSaves.enabled = !busy;
    NSMutableArray *lines = [NSMutableArray array];
    if (g_no_game_data) [lines addObject:g_no_game_data];
    if (!saves) [lines addObject:@"There are no saves to export yet."];
    self.note.text = [lines componentsJoinedByString:@"\n\n"]; self.note.hidden = !lines.count;
}
- (void)tell:(NSString *)title info:(NSString *)info {
    UIAlertController *a = [UIAlertController alertControllerWithTitle:title message:info preferredStyle:UIAlertControllerStyleAlert];
    [a addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
    [self presentViewController:a animated:YES completion:nil];
}
/* Runs work off the main thread (the backup copies the profile) with the buttons off, then done on the main thread. */
- (void)busy:(id (^)(NSError **))work done:(void (^)(id result, NSError *err))done {
    [self.spinner startAnimating]; [self refresh];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *err = nil; id result = work(&err);
        dispatch_async(dispatch_get_main_queue(), ^{ [self.spinner stopAnimating]; [self refresh]; done(result, err); });
    });
}
- (void)play:(id)sender {
    (void)sender;
    if (g_no_game_data || self.spinner.isAnimating) return;
    for (GCController *c in GCController.controllers) c.extendedGamepad.buttonA.pressedChangedHandler = nil;   // the game reads the pad itself
    [NSNotificationCenter.defaultCenter removeObserver:self];
    UIWindow *window = self.view.window;
    fprintf(stderr, "[xcx] start screen: Play\n");
    window.rootViewController = [XCXGameController new];
}
- (void)exportSaves:(id)sender {
    (void)sender;
    NSString *zip = [NSTemporaryDirectory() stringByAppendingPathComponent:xcx_saves_file_name([NSDate date])];
    NSString *device = UIDevice.currentDevice.name.length ? UIDevice.currentDevice.name : UIDevice.currentDevice.model;
    [self busy:^id(NSError **err) {
        [NSFileManager.defaultManager removeItemAtPath:zip error:nil];
        return xcx_saves_export(g_profile, zip, @TOTK_GAME_DIR, device, err) ? zip : nil;
    } done:^(id result, NSError *err) {
        if (!result) { [self tell:@"The saves were not exported" info:err.localizedDescription]; return; }
        fprintf(stderr, "[xcx] start screen: exported %s\n", zip.UTF8String);
        UIActivityViewController *share = [[UIActivityViewController alloc] initWithActivityItems:@[[NSURL fileURLWithPath:zip]] applicationActivities:nil];
        share.popoverPresentationController.sourceView = self.exportSaves;   // iPad: the sheet points at the button
        share.popoverPresentationController.sourceRect = self.exportSaves.bounds;
        share.completionWithItemsHandler = ^(UIActivityType type, BOOL completed, NSArray *items, NSError *error) {
            (void)type; (void)completed; (void)items; (void)error;
            [NSFileManager.defaultManager removeItemAtPath:zip error:nil];
        };
        [self presentViewController:share animated:YES completion:nil];
    }];
}
- (void)importSaves:(id)sender {
    (void)sender;
    UIDocumentPickerViewController *pick = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:@[UTTypeZIP] asCopy:YES];
    pick.delegate = self; pick.allowsMultipleSelection = NO;
    [self presentViewController:pick animated:YES completion:nil];
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    NSString *zip = urls.firstObject.path;   // a copy in the app's temporary folder (asCopy:YES), removed when done
    if (zip) dispatch_async(dispatch_get_main_queue(), ^{ [self confirmImport:zip]; });   // once the picker is gone
}
- (void)confirmImport:(NSString *)zip {
    NSError *err = nil;
    NSDictionary *m = xcx_saves_inspect(zip, @TOTK_GAME_DIR, &err);
    if (!m) { [NSFileManager.defaultManager removeItemAtPath:zip error:nil]; [self tell:@"The saves were not imported" info:err.localizedDescription]; return; }
    NSDate *when = xcx_saves_export_date(m);
    NSString *date = when ? [NSDateFormatter localizedStringFromDate:when dateStyle:NSDateFormatterMediumStyle timeStyle:NSDateFormatterShortStyle] : @"?";
    NSString *info = [NSString stringWithFormat:@"This replaces your current saves. A backup is made first.\n\nFrom: %@\nExported: %@\nGame version: %@",
                      m[@"device"], date, m[@"game_version_name"] ?: m[@"game_version"]];
    UIAlertController *ask = [UIAlertController alertControllerWithTitle:@"Import these saves?" message:info preferredStyle:UIAlertControllerStyleAlert];
    [ask addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:^(UIAlertAction *a) {
        (void)a; [NSFileManager.defaultManager removeItemAtPath:zip error:nil]; }]];
    [ask addAction:[UIAlertAction actionWithTitle:@"Import" style:UIAlertActionStyleDestructive handler:^(UIAlertAction *a) {
        (void)a;
        __block NSString *backup = nil;
        [self busy:^id(NSError **e) {
            NSString *b = nil;
            BOOL ok = xcx_saves_import(g_profile, zip, @TOTK_GAME_DIR, &b, nil, e);
            backup = b;
            [NSFileManager.defaultManager removeItemAtPath:zip error:nil];
            return ok ? @YES : nil;
        } done:^(id result, NSError *e) {
            if (!result) { [self tell:@"The saves were not imported" info:e.localizedDescription]; return; }
            fprintf(stderr, "[xcx] start screen: imported saves; backup %s\n", backup ? backup.UTF8String : "(no saves before)");
            [self tell:@"Saves imported"
                  info:backup ? [NSString stringWithFormat:@"Your previous saves were copied to Files › On My %@ › %@ › %@.", UIDevice.currentDevice.model, app_name(), backup.lastPathComponent]
                              : @"There were no previous saves to back up."];
        }];
    }]];
    [self presentViewController:ask animated:YES completion:nil];
}
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
@end

/* iOS 27 ends apps linked against its SDK that keep the window in the app delegate, so the window belongs to a scene. */
@interface XCXSceneDelegate : UIResponder <UIWindowSceneDelegate> @property(nonatomic,strong) UIWindow *window; @end
@implementation XCXSceneDelegate
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    (void)session; (void)options;
    if (![scene isKindOfClass:UIWindowScene.class]) return;
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.window.rootViewController = g_skip_start_screen ? [XCXGameController new] : [XCXStartController new];
    [self.window makeKeyAndVisible];
}
@end

/* Game audio after interruptions: a call, Siri or an alarm takes the audio session and the system stops the game's output
   unit. When an interruption ends the session is made active again (and the output restarted when the runtime can);
   becoming active does the same, for an interruption whose "ended" never came, and turns the idle timer off again. */
static BOOL g_audio_interrupted;
static void audio_resume(int recreate, const char *why) {
    NSError *err = nil;
    if (![AVAudioSession.sharedInstance setActive:YES error:&err]) fprintf(stderr,"[xcx-audio] audio session not active again (%s): %s\n",why,err.localizedDescription.UTF8String);
    g_audio_interrupted = NO;
    runtime_audio_output_restart(recreate);
}
static void audio_observe(void) {
    NSNotificationCenter *nc = NSNotificationCenter.defaultCenter; NSOperationQueue *main = NSOperationQueue.mainQueue;
    [nc addObserverForName:AVAudioSessionInterruptionNotification object:nil queue:main usingBlock:^(NSNotification *n) {
        NSUInteger type = [n.userInfo[AVAudioSessionInterruptionTypeKey] unsignedIntegerValue];
        fprintf(stderr,"[xcx-audio] audio session interruption %s\n",type == AVAudioSessionInterruptionTypeBegan ? "began" : "ended");
        if (type == AVAudioSessionInterruptionTypeBegan) g_audio_interrupted = YES; else audio_resume(0,"interruption ended");
    }];
    [nc addObserverForName:AVAudioSessionMediaServicesWereResetNotification object:nil queue:main usingBlock:^(NSNotification *n) {
        (void)n; fprintf(stderr,"[xcx-audio] media services were reset\n"); audio_resume(1,"media services reset");
    }];
    [nc addObserverForName:UIApplicationDidBecomeActiveNotification object:nil queue:main usingBlock:^(NSNotification *n) {
        (void)n; UIApplication.sharedApplication.idleTimerDisabled = YES;
        if (g_audio_interrupted) audio_resume(0,"became active during an interruption");
    }];
}

/* Memory and lifecycle readout in log.txt. iOS ends an app over its memory limit (jetsam) or for a watchdog without
   telling it, so the numbers left beforehand are the only record of what grew: every 10 s the footprint the limit is
   measured on (task_vm_info phys_footprint), the allowance left (os_proc_available_memory), the Metal device's
   allocations and the guest memory the game committed. Memory warnings, the thermal state, going to the background and
   the catchable termination signals are logged too (a SIGKILL from jetsam cannot be caught; its absence is the sign). */
uint64_t dm_mtl_l3_sample(uint32_t tick);
void runtime_guest_committed(uint64_t *heap_bytes, uint64_t *alias_mapped);
#include <mach/mach.h>
#include <os/proc.h>
static uint64_t footprint_bytes(void) {
    task_vm_info_data_t vi; mach_msg_type_number_t n = TASK_VM_INFO_COUNT;
    return task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&vi, &n) == KERN_SUCCESS ? vi.phys_footprint : 0;
}
static void mem_line(const char *why) {
    static CFAbsoluteTime t0; if (!t0) t0 = CFAbsoluteTimeGetCurrent();
    uint64_t heap = 0, alias = 0; runtime_guest_committed(&heap, &alias);
    fprintf(stderr, "[xcx-mem] %s t=%.0fs footprint=%llu MiB available=%llu MiB metal=%llu MiB guest=%llu MiB (heap %llu, mapped %llu) thermal=%ld\n",
            why, CFAbsoluteTimeGetCurrent() - t0, (unsigned long long)(footprint_bytes() >> 20), (unsigned long long)(os_proc_available_memory() >> 20),
            (unsigned long long)(dm_mtl_l3_sample(0) >> 20), (unsigned long long)((heap + alias) >> 20), (unsigned long long)(heap >> 20),
            (unsigned long long)(alias >> 20), (long)NSProcessInfo.processInfo.thermalState);
}
static void on_term_signal(int sig) {
    char m[64]; int n = snprintf(m, sizeof m, "[xcx] terminated by signal %d\n", sig); if (n > 0) write(2, m, (size_t)n);
    signal(sig, SIG_DFL); raise(sig);
}
static void lifecycle_observe(void) {
    for (int s = 0; s < 4; s++) signal((int[]){SIGTERM, SIGHUP, SIGINT, SIGALRM}[s], on_term_signal);
    mem_line("start");
    static dispatch_source_t timer;
    timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
    dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), 10 * NSEC_PER_SEC, NSEC_PER_SEC);
    dispatch_source_set_event_handler(timer, ^{ mem_line("every 10 s"); });
    dispatch_resume(timer);
    NSNotificationCenter *nc = NSNotificationCenter.defaultCenter; NSOperationQueue *main = NSOperationQueue.mainQueue;
    NSDictionary<NSNotificationName, NSString *> *events = @{
        UIApplicationDidReceiveMemoryWarningNotification: @"memory warning", UIApplicationWillResignActiveNotification: @"will resign active",
        UIApplicationDidEnterBackgroundNotification: @"entered background", UIApplicationWillEnterForegroundNotification: @"entering foreground",
        UIApplicationWillTerminateNotification: @"will terminate", NSProcessInfoThermalStateDidChangeNotification: @"thermal state changed" };
    for (NSNotificationName name in events) {
        NSString *what = events[name];
        [nc addObserverForName:name object:nil queue:main usingBlock:^(NSNotification *n) { (void)n; mem_line(what.UTF8String); }];
    }
}

@interface XCXApp : UIResponder <UIApplicationDelegate> @end
@implementation XCXApp
- (UISceneConfiguration *)application:(UIApplication *)application configurationForConnectingSceneSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    (void)application; (void)options;
    UISceneConfiguration *c = [[UISceneConfiguration alloc] initWithName:@"Default" sessionRole:session.role];
    c.delegateClass = XCXSceneDelegate.class; return c;
}
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options;
    // Controller input does not reset the idle timer; auto-lock would suspend the game mid-play.
    application.idleTimerDisabled = YES;
    audio_observe();
    /* Test launches from the Mac (devicectl --environment-variables) go straight into the game, as before the start
       screen: XCX_SKIP_START_SCREEN=1, or any of the test-only switches (an input script, autoload, another shader
       cache folder). Read before this function sets TOTK_SHADER_CACHE itself and clears TOTK_AUTOLOAD. */
    for (NSString *name in @[@"XCX_SKIP_START_SCREEN", @"TOTK_INPUT_SCRIPT", @"TOTK_AUTOLOAD", @"XC_SHADER_CACHE", @"TOTK_SHADER_CACHE"]) {
        const char *v = getenv(name.UTF8String);
        if (v && *v && strcmp(v, "0")) { g_skip_start_screen = YES; g_skip_reason = name; break; }
    }
    NSString *preferred = NSLocale.preferredLanguages.firstObject;   // as the Mac launcher (app/launcher.m)
    if (preferred.length) setenv("TOTK_LOCALE", preferred.UTF8String, 1);
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject;
    NSString *res = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData"];
    for (NSString *name in @[@"save", @"temp", @"shader-cache", @"game-slot", @"GameData"]) [fm createDirectoryAtPath:[docs stringByAppendingPathComponent:name] withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *log = [docs stringByAppendingPathComponent:@"log.txt"];
    if (freopen(log.fileSystemRepresentation,"w",stderr)) setvbuf(stderr,NULL,_IOLBF,0);
    lifecycle_observe();
    fprintf(stderr, "[xcx] start screen: %s\n", g_skip_start_screen ? [@"skipped, " stringByAppendingString:g_skip_reason].UTF8String : "shown");
    /* The app carries the RomFS index (GameData/romfs/runtime-index.bin, bound to the build by its SHA-256); the 14.3 GB
       image is installed once into Documents/GameData (romfs.bin, or romfs.bin.000, .001, ... in parts), by
       ios/tools/install_device.py --game-data or by copying it there in Finder / the Files app. Reinstalling the app keeps
       it. This runtime reads the index and the image from one folder (runtime/romfs.c TOTK_ROMFS), so the app's index is
       copied next to the image (a few kilobytes) when it differs. Excluded from iCloud backups. The runtime hashes the
       image once against the build's pin and keeps a record (TOTK_ROMFS_PROOF_DIR). */
    NSString *gameData = [docs stringByAppendingPathComponent:@"GameData"];
    /* Finder's file sharing (the device › Files) copies into the top of Documents: a romfs.bin put there is moved into
       GameData (a rename on the same volume, instant). */
    unsigned long long (^sizeOf)(NSString *) = ^unsigned long long (NSString *path) { return [[fm attributesOfItemAtPath:path error:nil] fileSize]; };
    NSString *dropped = [docs stringByAppendingPathComponent:@"romfs.bin"], *placed = [gameData stringByAppendingPathComponent:@"romfs.bin"];
    BOOL partial = NO;   // a romfs.bin still being copied (shorter than the build's image)
    if ([fm fileExistsAtPath:dropped] && ![fm fileExistsAtPath:placed]) {
        if (sizeOf(dropped) != ROMFS_IMAGE_SIZE) partial = YES;
        else { NSError *moveErr = nil;
               if (![fm moveItemAtPath:dropped toPath:placed error:&moveErr]) fprintf(stderr,"[xcx] could not move romfs.bin into GameData: %s\n",moveErr.localizedDescription.UTF8String); }
    }
    if ([fm fileExistsAtPath:placed] && sizeOf(placed) != ROMFS_IMAGE_SIZE) partial = YES;
    BOOL image = [fm fileExistsAtPath:placed] ||
                 [fm fileExistsAtPath:[gameData stringByAppendingPathComponent:@"romfs.bin.000"]];
    NSString *mark = [NSString stringWithContentsOfFile:[gameData stringByAppendingPathComponent:@"romfs.sha256"] encoding:NSUTF8StringEncoding error:nil];
    BOOL copying = partial || (mark && [mark stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].length != 64);   // install_device.py writes the hash last
    if (image && !copying) {
        [[NSURL fileURLWithPath:gameData isDirectory:YES] setResourceValue:@YES forKey:NSURLIsExcludedFromBackupKey error:nil];
        NSString *from = [res stringByAppendingPathComponent:@"romfs/runtime-index.bin"], *to = [gameData stringByAppendingPathComponent:@"runtime-index.bin"];
        NSData *want = [NSData dataWithContentsOfFile:from];
        if (want && ![[NSData dataWithContentsOfFile:to] isEqualToData:want] && ![want writeToFile:to atomically:YES])
            fprintf(stderr, "[xcx] could not copy the RomFS index to %s\n", to.UTF8String);
        setenv("TOTK_ROMFS",gameData.fileSystemRepresentation,1);
    } else {
        /* No image to play from: said on the screen instead of the game ending at once (runtime_fail exits). */
        NSString *app = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleDisplayName"] ?: @"Xenoblade Chronicles X";
        g_no_game_data = copying || image
            ? [NSString stringWithFormat:@"The game data (romfs.bin, %.1f GB) is still being copied to Files › On My iPhone › %@. Open the game again when it is done.", ROMFS_IMAGE_SIZE / 1e9, app]
            : [NSString stringWithFormat:@"No game data. Copy romfs.bin from the Mac's work folder (extracted/" TOTK_GAME_DIR "/romfs/romfs.bin) to "
                                          "this app: with games/xcx/ios/tools/install_device.py --game-data, or in Finder (the device › Files: "
                                          "drag romfs.bin onto %@), then open the game again.", app];
        fprintf(stderr, "[xcx] no game image: %s\n", g_no_game_data.UTF8String);
    }
    setenv("TOTK_OPERATION_MODE","handheld",1);
    // Game language: the Settings app (Settings.bundle › TOTK_LANG) stores the choice in our defaults; empty means the
    // system language. iOS does not honour Info.plist LSEnvironment, so the value is applied here; overwrite=0 keeps
    // devicectl --environment-variables winning when testing from the Mac.
    NSString *lang = [NSUserDefaults.standardUserDefaults stringForKey:@"TOTK_LANG"];
    if (lang.length>0&&lang.length<8) setenv("TOTK_LANG",lang.UTF8String,0);
    setenv("TOTK_ROMFS_PATCHES","0",1);   // XCX has no build-made RomFS overlays (runtime/romfs.c)
    setenv("TOTK_ROMFS_MODS","0",1);
    setenv("TOTK_SHARED_FONTS",[res stringByAppendingPathComponent:@"shared-fonts"].fileSystemRepresentation,1);
    setenv("TOTK_SHADER_SEED_DIR",[res stringByAppendingPathComponent:@"shader-seed"].fileSystemRepresentation,1);
    /* One folder per translation chain, as on the Mac (app/launcher.m): the runtime refuses translations of another
       chain; other chains' folders are only cache and are removed in the background. */
    NSString *cacheRoot = [docs stringByAppendingPathComponent:@"shader-cache"], *chainDir = @"rt-" DMSH_CHAIN;
    NSString *cache = [cacheRoot stringByAppendingPathComponent:chainDir];
    const char *testCache = getenv("XC_SHADER_CACHE");
    if (!testCache || !*testCache) testCache = getenv("TOTK_SHADER_CACHE");   // (older name) test launches may name another folder in Documents
    if (testCache && *testCache && !strstr(testCache, "..")) cache = [docs stringByAppendingPathComponent:@(testCache)];
    [fm createDirectoryAtPath:cache withIntermediateDirectories:YES attributes:nil error:nil];
    setenv("TOTK_SHADER_CACHE",cache.fileSystemRepresentation,1);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
        NSFileManager *files = [NSFileManager new]; NSUInteger removed = 0;
        for (NSString *name in [files contentsOfDirectoryAtPath:cacheRoot error:nil] ?: @[]) {
            if ([name isEqualToString:chainDir]) continue;
            if ([files removeItemAtPath:[cacheRoot stringByAppendingPathComponent:name] error:nil]) removed++;
        }
        if (removed) fprintf(stderr,"[shader-cache] removed %lu entries of earlier translation chains\n",(unsigned long)removed);
    });
    // The variants the device missed (totk_shader_contrib.h), in the Files app; nothing is sent anywhere.
    setenv("TOTK_SHADER_CONTRIB",[docs stringByAppendingPathComponent:@"shader-list-contribution.txt"].fileSystemRepresentation,1);
    setenv("DM_NVN_SHMAP",[res stringByAppendingPathComponent:@"shader-seed/shader_map.tsv"].fileSystemRepresentation,1);
    setenv("DM_MSL_DIR",[res stringByAppendingPathComponent:@"shader-seed"].fileSystemRepresentation,1);
    // Same player environment as the Mac launcher (app/launcher.m); the bundle is read-only, so state goes to Documents.
    g_profile = [docs stringByAppendingPathComponent:@"save"];   // also the start screen's (Export / Import Saves)
    setenv("TOTK_PROFILE_DIR",g_profile.fileSystemRepresentation,1);
    setenv("TOTK_GAME_SLOT_DIR",[docs stringByAppendingPathComponent:@"game-slot"].fileSystemRepresentation,1);
    setenv("TOTK_ROMFS_PROOF_DIR",docs.fileSystemRepresentation,1);   // hash the 14 GB RomFS once, not on every launch
    for (NSString *name in @[@"TOTK_GPU_ALLOW_SUBMIT",@"TOTK_GPU_WIDEN",@"TOTK_GPU_BLOCKRT",@"TOTK_GPU_MIDCLEAR"]) setenv(name.UTF8String,"1",1);
    setenv("DM_PRESENT_LINK_FALLBACK","1",1);
    setenv("TOTK_SLOT_OWNER","user",0); setenv("TOTK_SLOT_PURPOSE","player",0);
    unsetenv("TOTK_AUTOLOAD"); unsetenv("TOTK_HEADLESS");
    /* Code patches are fixed at build time on iOS: the IPA's main text carries the 60 fps patch's sites (build_ipa.py
       exports it with XCX_PATCHES=60fps), so the runtime checks them and the Settings switch (Settings.bundle ›
       XCX_FRAME_RATE, 30 by default) only picks the values it reads: XCX_FPS60=0 keeps the game's vsync count 2 and its
       own frame time, i.e. the original 30 fps. A launch environment value (devicectl --environment-variables) wins. */
    setenv("XCX_PATCHES", "60fps", 1);
    { NSString *fr = [NSUserDefaults.standardUserDefaults stringForKey:@"XCX_FRAME_RATE"];
      setenv("XCX_FPS60", fr.integerValue == 60 ? "1" : "0", 0);
      fprintf(stderr, "[xcx] frame rate setting: %s (XCX_FPS60=%s)\n", fr.length ? fr.UTF8String : "30 (default)", getenv("XCX_FPS60")); }
    chdir(docs.fileSystemRepresentation);
    host_argv[0] = strdup("XCX"); host_argv[1] = strdup(res.fileSystemRepresentation); host_argv[2] = strdup("boot");
    return YES;   // the window is made when the window scene connects (XCXSceneDelegate)
}
@end

int main(int argc, char **argv) { @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(XCXApp.class)); } }
