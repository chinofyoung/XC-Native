/* Save export / import: one zip with the files of the game's save folder and a manifest, shared by the Mac launcher
   (app/launcher.m) and the iPhone / iPad app (ios/Sources). Foundation, zlib and CommonCrypto only: no UIKit or AppKit,
   no processes (iOS cannot start one), so both build it as it is (the Mac: the Makefile's launcher rule, -lz).

   Where the saves are: <profile>/save/<id>/sts/game/ (gamedata01, gamedata02, gamedataa, systemdata, avatarmakedata,
   socialdata and the .tmb thumbnails). <profile> is the runtime's TOTK_PROFILE_DIR (Mac: ~/Library/Application Support/
   XCNative/XCX/profile; iOS: Documents/save). <id> is the local account's id, as the runtime names it
   (runtime/fs_host.c init): the 16 bytes of <profile>/account.uid read as two little-endian 64-bit words lo, hi and
   printed "%016llx%016llx" hi, lo. It differs between devices, so an import writes into this device's folder.
   account.uid, pseudo-device.id, pso_user.tsv, cache/ and temp/ are this device's: never exported, never replaced.

   The zip (XCX-saves-<yyyy-MM-dd-HHmm>.zip): xcx-saves.json first, then each save file flat (no folders), deflated.
   xcx-saves.json: {"format": 1, "game_version": "v101" | "v200", "game_version_name": "1.0.1" | "2.0.0",
   "device": <name>, "exported": <ISO 8601 local time>, "files": [{"name", "size", "sha256"}, ...]}.

   Import: everything is checked before anything is written (manifest present, format known, only safe names, each
   file listed once and present, sizes and SHA-256 match, the CRC of every entry); a 2.0.0 export is refused by a 1.0.1
   app (1.0.1 into 2.0.0 is fine). Then the whole profile is copied to <profile>-<version>-backup-<date> next to it (as
   the builder's Back Up Saves), the new files are written into <profile>/temp/ and swapped in for sts/game in one
   rename (renamex_np RENAME_SWAP), so a failure leaves the old saves or the new ones, never a mix. The caller makes sure
   the game is not running. Messages (NSError localizedDescription) are short English sentences for the player. */
#pragma once
#import <Foundation/Foundation.h>

extern NSString *const XCXSavesErrorDomain;
typedef NS_ENUM(NSInteger, XCXSavesError) {
    XCXSavesErrorNoSaves = 1,     // export: no save folder or no files in it
    XCXSavesErrorNotExport,       // not a zip, or no xcx-saves.json
    XCXSavesErrorDamaged,         // a hash, size, CRC or name does not match; an unexpected file
    XCXSavesErrorNewerGame,       // a 2.0.0 export into a 1.0.1 app (or an unknown version)
    XCXSavesErrorNewerFormat,     // xcx-saves.json of a later format
    XCXSavesErrorWrite,           // the disk: reading the saves, writing the zip, the backup or the new saves
};

/* The manifest's file name inside the zip, and the format this code writes. */
#define XCX_SAVES_MANIFEST @"xcx-saves.json"
#define XCX_SAVES_FORMAT 1

/* <profile>/save/<id>/sts/game for this device's account. create: when account.uid is missing, make it the way the
   runtime does (runtime/account.c: 16 random bytes, not all zero, mode 0600) and make the folders (0700); without
   create a missing account or folder is an XCXSavesErrorNoSaves error. */
NSString *xcx_saves_folder(NSString *profile, BOOL create, NSError **error);

/* The names of the save files in the folder (regular files with a safe name, sorted); empty when there is none. */
NSArray<NSString *> *xcx_saves_list(NSString *profile);

/* "XCX-saves-2026-10-28-1530.zip" for the given time (local time zone). */
NSString *xcx_saves_file_name(NSDate *date);

/* "1.0.1" for "v101", "2.0.0" for "v200", nil for anything else. */
NSString *xcx_saves_version_name(NSString *game_dir);

/* Writes the zip (atomically: a temporary file renamed into place). game_dir: the app's TOTK_GAME_DIR (v101 / v200);
   device: a name for the player to recognise (the Mac's computer name, the iPhone's model). */
BOOL xcx_saves_export(NSString *profile, NSString *zip_path, NSString *game_dir, NSString *device, NSError **error);

/* Reads and checks the zip as an import would, without writing anything; returns its manifest (keys "device",
   "exported", "game_version", "game_version_name", "files") or nil with the reason. game_dir: this app's. */
NSDictionary *xcx_saves_inspect(NSString *zip_path, NSString *game_dir, NSError **error);

/* The manifest's export time as a date (nil when unreadable). */
NSDate *xcx_saves_export_date(NSDictionary *manifest);

/* Checks the zip (as xcx_saves_inspect), backs the profile up, then replaces this device's saves with the zip's.
   *backup: the backup folder, or nil when there were no saves to back up; *folder: the save folder written. */
BOOL xcx_saves_import(NSString *profile, NSString *zip_path, NSString *game_dir, NSString **backup, NSString **folder,
                      NSError **error);
