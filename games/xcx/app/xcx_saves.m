/* Save export / import (xcx_saves.h): the save folder, a small zip writer and reader (stored or deflate through zlib,
   no zip64, no encryption) and the checks. */
#import "xcx_saves.h"
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>

NSString *const XCXSavesErrorDomain = @"org.xcnative.xcx.saves";

/* Limits for reading: a save file is under 1 MB and the folder has about ten. */
#define MAX_ENTRIES 64
#define MAX_FILE_SIZE (64u << 20)
#define MAX_ZIP_SIZE (512ull << 20)

static BOOL fail(NSError **error, XCXSavesError code, NSString *message) {
    if (error) *error = [NSError errorWithDomain:XCXSavesErrorDomain code:code userInfo:@{NSLocalizedDescriptionKey: message}];
    return NO;
}
static NSString *errno_text(void) { return @(strerror(errno)); }

/* ---------- the save folder ---------- */

/* A save file's name: 1 to 64 characters of letters, digits, '_', '-', '.', starting with a letter or digit, no "..".
   This rules out folders, absolute paths and any way out of the folder; the manifest's own name is not one. */
static BOOL safe_name(NSString *name) {
    if (![name isKindOfClass:NSString.class] || name.length < 1 || name.length > 64) return NO;
    if ([name isEqualToString:XCX_SAVES_MANIFEST] || [name containsString:@".."]) return NO;
    for (NSUInteger i = 0; i < name.length; i++) {
        unichar c = [name characterAtIndex:i];
        BOOL alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (!alnum && (i == 0 || (c != '_' && c != '-' && c != '.'))) return NO;
    }
    return YES;
}

static BOOL make_dirs(NSString *path) {
    return [NSFileManager.defaultManager createDirectoryAtPath:path withIntermediateDirectories:YES
                                                    attributes:@{NSFilePosixPermissions: @0700} error:nil];
}

/* The account id as the runtime prints it (runtime/fs_host.c init), from account.uid (runtime/account.c). */
static NSString *account_id(NSString *profile, BOOL create, NSError **error) {
    NSString *path = [profile stringByAppendingPathComponent:@"account.uid"];
    uint8_t b[16];
    int fd = open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    if (fd < 0 && errno == ENOENT && create) {
        if (!make_dirs(profile)) { fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ cannot be made.", profile]); return nil; }
        int w = open(path.fileSystemRepresentation, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
        if (w >= 0) {
            do arc4random_buf(b, sizeof b); while (!memcmp(b, (uint8_t[16]){0}, sizeof b));
            BOOL ok = write(w, b, sizeof b) == (ssize_t)sizeof b && !fsync(w);
            close(w);
            if (!ok) { unlink(path.fileSystemRepresentation); fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ cannot be written.", path]); return nil; }
        }
        fd = open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);   // also when another writer made it first
    }
    if (fd < 0) {
        fail(error, errno == ENOENT ? XCXSavesErrorNoSaves : XCXSavesErrorWrite,
             errno == ENOENT ? @"There are no saves yet." : [NSString stringWithFormat:@"%@ cannot be read: %@.", path, errno_text()]);
        return nil;
    }
    struct stat st;
    BOOL ok = !fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_size == 16 && pread(fd, b, 16, 0) == 16 && memcmp(b, (uint8_t[16]){0}, 16);
    close(fd);
    if (!ok) { fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ is damaged; start the game once.", path]); return nil; }
    uint64_t lo = 0, hi = 0;
    for (int i = 7; i >= 0; i--) { lo = lo << 8 | b[i]; hi = hi << 8 | b[8 + i]; }
    return [NSString stringWithFormat:@"%016llx%016llx", (unsigned long long)hi, (unsigned long long)lo];
}

NSString *xcx_saves_folder(NSString *profile, BOOL create, NSError **error) {
    NSString *uid = account_id(profile, create, error);
    if (!uid) return nil;
    NSString *folder = [profile stringByAppendingFormat:@"/save/%@/sts/game", uid];
    BOOL dir = NO;
    if ([NSFileManager.defaultManager fileExistsAtPath:folder isDirectory:&dir] && dir) return folder;
    if (!create) { fail(error, XCXSavesErrorNoSaves, @"There are no saves yet."); return nil; }
    if (!make_dirs(folder)) { fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ cannot be made.", folder]); return nil; }
    return folder;
}

static NSArray<NSString *> *list_folder(NSString *folder) {
    NSMutableArray *out = [NSMutableArray array];
    for (NSString *name in [NSFileManager.defaultManager contentsOfDirectoryAtPath:folder error:nil] ?: @[]) {
        struct stat st;
        if (safe_name(name) && !lstat([folder stringByAppendingPathComponent:name].fileSystemRepresentation, &st) && S_ISREG(st.st_mode))
            [out addObject:name];
    }
    return [out sortedArrayUsingSelector:@selector(compare:)];
}

NSArray<NSString *> *xcx_saves_list(NSString *profile) {
    NSString *folder = xcx_saves_folder(profile, NO, nil);
    return folder ? list_folder(folder) : @[];
}

NSString *xcx_saves_file_name(NSDate *date) {
    NSDateFormatter *f = [NSDateFormatter new];
    f.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"]; f.dateFormat = @"yyyy-MM-dd-HHmm";
    return [NSString stringWithFormat:@"XCX-saves-%@.zip", [f stringFromDate:date]];
}

static NSArray<NSString *> *versions(void) { return @[@"v101", @"v200"]; }   // oldest first
NSString *xcx_saves_version_name(NSString *game_dir) {
    return @{@"v101": @"1.0.1", @"v200": @"2.0.0"}[game_dir];
}

static NSString *sha256_hex(NSData *data) {
    uint8_t d[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, d);
    NSMutableString *s = [NSMutableString stringWithCapacity:2 * sizeof d];
    for (size_t i = 0; i < sizeof d; i++) [s appendFormat:@"%02x", d[i]];
    return s;
}

/* ---------- zip ---------- */

static void put16(NSMutableData *d, uint32_t v) { uint8_t b[2] = {v & 0xff, (v >> 8) & 0xff}; [d appendBytes:b length:2]; }
static void put32(NSMutableData *d, uint32_t v) { put16(d, v & 0xffff); put16(d, v >> 16); }
static uint32_t get16(const uint8_t *p) { return p[0] | (uint32_t)p[1] << 8; }
static uint32_t get32(const uint8_t *p) { return get16(p) | get16(p + 2) << 16; }

/* Raw deflate (zip method 8); nil when it does not make the data smaller (stored then). */
static NSData *deflate_raw(NSData *in) {
    z_stream z; memset(&z, 0, sizeof z);
    if (deflateInit2(&z, Z_BEST_COMPRESSION, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) != Z_OK) return nil;
    uLong cap = deflateBound(&z, (uLong)in.length);
    NSMutableData *out = [NSMutableData dataWithLength:cap];
    z.next_in = (Bytef *)in.bytes; z.avail_in = (uInt)in.length;
    z.next_out = out.mutableBytes; z.avail_out = (uInt)cap;
    int r = deflate(&z, Z_FINISH);
    uLong n = z.total_out;
    deflateEnd(&z);
    if (r != Z_STREAM_END || n >= in.length) return nil;
    out.length = n;
    return out;
}

/* entries: name -> contents, written in the order of `order`. Unix permissions 0600, the current time. */
static NSData *zip_write(NSArray<NSString *> *order, NSDictionary<NSString *, NSData *> *entries, NSDate *when) {
    NSDateComponents *c = [NSCalendar.currentCalendar components:NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay |
                           NSCalendarUnitHour | NSCalendarUnitMinute | NSCalendarUnitSecond fromDate:when];
    uint32_t dtime = (uint32_t)(c.hour << 11 | c.minute << 5 | c.second / 2);
    uint32_t ddate = (uint32_t)((MAX(c.year, 1980) - 1980) << 9 | c.month << 5 | c.day);
    NSMutableData *zip = [NSMutableData data], *central = [NSMutableData data];
    for (NSString *name in order) {
        NSData *raw = entries[name], *packed = deflate_raw(raw);
        NSData *name8 = [name dataUsingEncoding:NSUTF8StringEncoding];
        uint32_t crc = (uint32_t)crc32(0, raw.bytes, (uInt)raw.length), offset = (uint32_t)zip.length;
        uint32_t method = packed ? 8 : 0; NSData *body = packed ?: raw;
        put32(zip, 0x04034b50); put16(zip, 20); put16(zip, 0); put16(zip, method); put16(zip, dtime); put16(zip, ddate);
        put32(zip, crc); put32(zip, (uint32_t)body.length); put32(zip, (uint32_t)raw.length);
        put16(zip, (uint32_t)name8.length); put16(zip, 0); [zip appendData:name8]; [zip appendData:body];
        put32(central, 0x02014b50); put16(central, 3 << 8 | 20); put16(central, 20); put16(central, 0); put16(central, method);
        put16(central, dtime); put16(central, ddate); put32(central, crc); put32(central, (uint32_t)body.length);
        put32(central, (uint32_t)raw.length); put16(central, (uint32_t)name8.length); put16(central, 0); put16(central, 0);
        put16(central, 0); put16(central, 0); put32(central, (uint32_t)(S_IFREG | 0600) << 16); put32(central, offset);
        [central appendData:name8];
    }
    uint32_t cd = (uint32_t)zip.length;
    [zip appendData:central];
    put32(zip, 0x06054b50); put16(zip, 0); put16(zip, 0); put16(zip, (uint32_t)order.count); put16(zip, (uint32_t)order.count);
    put32(zip, (uint32_t)central.length); put32(zip, cd); put16(zip, 0);
    return zip;
}

/* Every entry of a zip (stored or deflate; Finder's Compress makes deflate with data descriptors, read through the
   central directory). Returns name -> contents in *out and the names in order, or a reason. Directory entries ("x/")
   are returned with empty contents so the caller can refuse them by name. */
static NSString *zip_read(NSData *zip, NSMutableArray<NSString *> *order, NSMutableDictionary<NSString *, NSData *> *out) {
    const uint8_t *p = zip.bytes; size_t n = zip.length;
    if (n < 22) return @"it is too short to be a zip";
    size_t eocd = SIZE_MAX;
    for (size_t i = n - 22 + 1; i-- > 0 && n - i <= 22 + 0xffff;) if (get32(p + i) == 0x06054b50) { eocd = i; break; }
    if (eocd == SIZE_MAX) return @"it is not a zip";
    uint32_t count = get16(p + eocd + 10), cd_size = get32(p + eocd + 12), cd = get32(p + eocd + 16);
    if (get16(p + eocd + 4) || get16(p + eocd + 6) || count != get16(p + eocd + 8)) return @"it is a zip in several parts";
    if (count == 0xffff || cd == 0xffffffffu || cd_size == 0xffffffffu) return @"it is a zip64 archive";
    if (count > MAX_ENTRIES) return @"it holds too many files";
    if ((uint64_t)cd + cd_size > eocd) return @"its directory is damaged";
    size_t at = cd;
    for (uint32_t k = 0; k < count; k++) {
        if (at + 46 > (size_t)cd + cd_size || get32(p + at) != 0x02014b50) return @"its directory is damaged";
        uint32_t flags = get16(p + at + 8), method = get16(p + at + 10), crc = get32(p + at + 16);
        uint32_t csize = get32(p + at + 20), usize = get32(p + at + 24), nlen = get16(p + at + 28);
        uint32_t xlen = get16(p + at + 30), clen = get16(p + at + 32), local = get32(p + at + 42);
        if (at + 46 + nlen + xlen + clen > (size_t)cd + cd_size) return @"its directory is damaged";
        NSString *name = [[NSString alloc] initWithBytes:p + at + 46 length:nlen encoding:NSUTF8StringEncoding];
        at += 46 + nlen + xlen + clen;
        if (!name.length) return @"it has a file without a usable name";
        if (out[name]) return [NSString stringWithFormat:@"it has %@ twice", name];
        if (flags & 1) return @"it is encrypted";
        if (usize > MAX_FILE_SIZE || csize > MAX_FILE_SIZE) return [NSString stringWithFormat:@"%@ is too large", name];
        if ((uint64_t)local + 30 > cd || get32(p + local) != 0x04034b50) return @"its contents are damaged";
        uint64_t data = (uint64_t)local + 30 + get16(p + local + 26) + get16(p + local + 28);
        if (data + csize > cd) return @"its contents are damaged";
        NSMutableData *body = [NSMutableData dataWithLength:usize];
        if (method == 0) {
            if (csize != usize) return [NSString stringWithFormat:@"%@ is damaged", name];
            memcpy(body.mutableBytes, p + data, usize);
        } else if (method == 8) {
            z_stream z; memset(&z, 0, sizeof z);
            if (inflateInit2(&z, -15) != Z_OK) return @"zlib failed";
            uint8_t spare;   // a stream that would write past usize ends with avail_out 0 and no Z_STREAM_END
            z.next_in = (Bytef *)(p + data); z.avail_in = csize;
            z.next_out = usize ? body.mutableBytes : &spare; z.avail_out = usize ? usize : 0;
            int r = inflate(&z, Z_FINISH);
            uLong got = z.total_out;
            inflateEnd(&z);
            if (r != Z_STREAM_END || got != usize) return [NSString stringWithFormat:@"%@ is damaged", name];
        } else return [NSString stringWithFormat:@"%@ uses a compression this app does not read", name];
        if ((uint32_t)crc32(0, body.bytes, (uInt)body.length) != crc) return [NSString stringWithFormat:@"%@ is damaged (CRC)", name];
        [order addObject:name]; out[name] = body;
    }
    return nil;
}

/* ---------- export ---------- */

BOOL xcx_saves_export(NSString *profile, NSString *zip_path, NSString *game_dir, NSString *device, NSError **error) {
    NSString *version = xcx_saves_version_name(game_dir);
    if (!version) return fail(error, XCXSavesErrorNewerGame, [NSString stringWithFormat:@"Unknown game version %@.", game_dir]);
    NSError *ferr = nil;
    NSString *folder = xcx_saves_folder(profile, NO, &ferr);
    if (!folder && ferr.code != XCXSavesErrorNoSaves) { if (error) *error = ferr; return NO; }
    NSArray<NSString *> *names = folder ? list_folder(folder) : @[];
    if (!names.count) return fail(error, XCXSavesErrorNoSaves, @"There are no saves to export yet.");
    NSMutableDictionary<NSString *, NSData *> *entries = [NSMutableDictionary dictionary];
    NSMutableArray *files = [NSMutableArray array];
    for (NSString *name in names) {
        NSData *d = [NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:name]];
        if (!d) return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ cannot be read.", name]);
        if (d.length > MAX_FILE_SIZE) return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"%@ is too large.", name]);
        entries[name] = d;
        [files addObject:@{@"name": name, @"size": @(d.length), @"sha256": sha256_hex(d)}];
    }
    NSDate *now = [NSDate date];
    NSISO8601DateFormatter *iso = [NSISO8601DateFormatter new]; iso.timeZone = NSTimeZone.localTimeZone;
    NSDictionary *manifest = @{@"format": @XCX_SAVES_FORMAT, @"game_version": game_dir, @"game_version_name": version,
                               @"device": device.length ? device : @"?", @"exported": [iso stringFromDate:now], @"files": files};
    NSData *json = [NSJSONSerialization dataWithJSONObject:manifest options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:nil];
    entries[XCX_SAVES_MANIFEST] = json;
    NSData *zip = zip_write([@[XCX_SAVES_MANIFEST] arrayByAddingObjectsFromArray:names], entries, now);
    NSError *werr = nil;
    if (![zip writeToFile:zip_path options:NSDataWritingAtomic error:&werr])
        return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"The zip cannot be written: %@", werr.localizedDescription]);
    return YES;
}

/* ---------- import ---------- */

/* The zip's manifest and files, checked; nil with the reason. */
static NSDictionary *read_export(NSString *zip_path, NSString *game_dir, NSDictionary<NSString *, NSData *> **files_out, NSError **error) {
    NSString *mine = xcx_saves_version_name(game_dir);
    if (!mine) { fail(error, XCXSavesErrorNewerGame, [NSString stringWithFormat:@"Unknown game version %@.", game_dir]); return nil; }
    NSDictionary *attrs = [NSFileManager.defaultManager attributesOfItemAtPath:zip_path error:nil];
    if (!attrs) { fail(error, XCXSavesErrorNotExport, @"The file cannot be read."); return nil; }
    if (attrs.fileSize > MAX_ZIP_SIZE) { fail(error, XCXSavesErrorNotExport, @"This file is too large to be a saves export."); return nil; }
    NSData *zip = [NSData dataWithContentsOfFile:zip_path options:NSDataReadingMappedIfSafe error:nil];
    if (!zip) { fail(error, XCXSavesErrorNotExport, @"The file cannot be read."); return nil; }
    NSMutableArray<NSString *> *order = [NSMutableArray array];
    NSMutableDictionary<NSString *, NSData *> *entries = [NSMutableDictionary dictionary];
    NSString *why = zip_read(zip, order, entries);
    if (why) { fail(error, XCXSavesErrorNotExport, [NSString stringWithFormat:@"This file cannot be read as a zip: %@.", why]); return nil; }
    NSData *json = entries[XCX_SAVES_MANIFEST];
    if (!json) { fail(error, XCXSavesErrorNotExport, @"This zip is not a saves export (it has no xcx-saves.json)."); return nil; }
    id m = [NSJSONSerialization JSONObjectWithData:json options:0 error:nil];
    NSString *bad = @"xcx-saves.json in this zip is damaged.";
    if (![m isKindOfClass:NSDictionary.class] || ![m[@"format"] isKindOfClass:NSNumber.class]) { fail(error, XCXSavesErrorDamaged, bad); return nil; }
    NSInteger format = [m[@"format"] integerValue];
    if (format > XCX_SAVES_FORMAT) {
        fail(error, XCXSavesErrorNewerFormat, [NSString stringWithFormat:@"This export was made by a newer XC-Native (format %ld). Update this app first.", (long)format]);
        return nil;
    }
    if (format < 1 || ![m[@"files"] isKindOfClass:NSArray.class] || ![m[@"game_version"] isKindOfClass:NSString.class]) { fail(error, XCXSavesErrorDamaged, bad); return nil; }
    NSUInteger theirs = [versions() indexOfObject:m[@"game_version"]], ours = [versions() indexOfObject:game_dir];
    if (theirs == NSNotFound) {
        fail(error, XCXSavesErrorNewerGame, [NSString stringWithFormat:@"These saves are from a game version this app does not know (%@).", m[@"game_version"]]);
        return nil;
    }
    if (theirs > ours) {
        fail(error, XCXSavesErrorNewerGame, [NSString stringWithFormat:@"These saves are from the game's %@ update. This app runs %@, which may not load them: "
                                             "use an app built for %@.", xcx_saves_version_name(m[@"game_version"]), mine, xcx_saves_version_name(m[@"game_version"])]);
        return nil;
    }
    NSMutableDictionary<NSString *, NSData *> *files = [NSMutableDictionary dictionary];
    for (id f in m[@"files"]) {
        if (![f isKindOfClass:NSDictionary.class] || ![f[@"sha256"] isKindOfClass:NSString.class] || ![f[@"size"] isKindOfClass:NSNumber.class]) { fail(error, XCXSavesErrorDamaged, bad); return nil; }
        NSString *name = f[@"name"];
        if (!safe_name(name)) { fail(error, XCXSavesErrorDamaged, [NSString stringWithFormat:@"This zip names a file a saves export never has: %@.", name]); return nil; }
        if (files[name]) { fail(error, XCXSavesErrorDamaged, [NSString stringWithFormat:@"xcx-saves.json lists %@ twice.", name]); return nil; }
        NSData *d = entries[name];
        if (!d) { fail(error, XCXSavesErrorDamaged, [NSString stringWithFormat:@"%@ is listed in xcx-saves.json but missing from the zip.", name]); return nil; }
        if (d.length != [f[@"size"] unsignedLongLongValue] || ![sha256_hex(d) isEqualToString:[f[@"sha256"] lowercaseString]]) {
            fail(error, XCXSavesErrorDamaged, [NSString stringWithFormat:@"%@ in this zip is damaged (its SHA-256 does not match).", name]);
            return nil;
        }
        files[name] = d;
    }
    for (NSString *name in order)
        if (![name isEqualToString:XCX_SAVES_MANIFEST] && !files[name]) {
            fail(error, XCXSavesErrorDamaged, [NSString stringWithFormat:@"This zip holds a file that is not in xcx-saves.json: %@.", name]);
            return nil;
        }
    if (!files.count) { fail(error, XCXSavesErrorDamaged, @"This export holds no saves."); return nil; }
    if (files_out) *files_out = files;
    return m;
}

NSDictionary *xcx_saves_inspect(NSString *zip_path, NSString *game_dir, NSError **error) {
    return read_export(zip_path, game_dir, NULL, error);
}

NSDate *xcx_saves_export_date(NSDictionary *manifest) {
    id s = manifest[@"exported"];
    return [s isKindOfClass:NSString.class] ? [[NSISO8601DateFormatter new] dateFromString:s] : nil;
}

static BOOL write_file(NSString *path, NSData *d) {
    int fd = open(path.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) return NO;
    const uint8_t *p = d.bytes; size_t left = d.length;
    while (left) { ssize_t w = write(fd, p, left); if (w <= 0) { if (w < 0 && errno == EINTR) continue; close(fd); return NO; } p += w; left -= (size_t)w; }
    BOOL ok = !fcntl(fd, F_FULLFSYNC) || !fsync(fd);
    return !close(fd) && ok;
}
static void sync_dir(NSString *dir) { int fd = open(dir.fileSystemRepresentation, O_RDONLY); if (fd >= 0) { fsync(fd); close(fd); } }

BOOL xcx_saves_import(NSString *profile, NSString *zip_path, NSString *game_dir, NSString **backup, NSString **folder, NSError **error) {
    if (backup) *backup = nil;
    if (folder) *folder = nil;
    NSDictionary<NSString *, NSData *> *files = nil;
    if (!read_export(zip_path, game_dir, &files, error)) return NO;
    NSFileManager *fm = NSFileManager.defaultManager;

    /* The backup first, from what is there before anything is made: the whole profile, as the builder's Back Up Saves
       (profile-<version>-backup-<date>, next to it). Nothing to back up when there are no saves. */
    NSString *old = xcx_saves_folder(profile, NO, nil), *copy = nil;
    if (old && list_folder(old).count) {
        NSDateFormatter *f = [NSDateFormatter new];
        f.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"]; f.dateFormat = @"yyyy-MM-dd-HHmmss";
        NSString *base = [profile.stringByDeletingLastPathComponent stringByAppendingPathComponent:
                          [profile.lastPathComponent stringByAppendingFormat:@"-%@-backup-%@", xcx_saves_version_name(game_dir), [f stringFromDate:[NSDate date]]]];
        copy = base;
        for (int i = 2; [fm fileExistsAtPath:copy]; i++) copy = [base stringByAppendingFormat:@"-%d", i];
        NSError *cerr = nil;
        if (![fm copyItemAtPath:profile toPath:copy error:&cerr])
            return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"The current saves could not be backed up (%@). Nothing was changed.", cerr.localizedDescription]);
    }
    NSString *target = xcx_saves_folder(profile, YES, error);   // makes account.uid and the folders when missing
    if (!target) return NO;

    /* The new files in a folder of the profile's temp/ (the runtime empties temp/ at every start, so nothing is left
       behind there), then swapped in for the save folder in one step. */
    NSString *temp = [profile stringByAppendingPathComponent:@"temp"];
    NSString *staging = [temp stringByAppendingFormat:@"/import-%d-%08x", getpid(), arc4random()];
    NSString *(^kept)(void) = ^NSString *{ return copy ? [NSString stringWithFormat:@" A backup of the saves before the import is at %@.", copy] : @""; };
    if (!make_dirs(temp) || mkdir(staging.fileSystemRepresentation, 0700)) {
        return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"The saves could not be written (%@: %@). Nothing was changed.%@", staging, errno_text(), kept()]);
    }
    for (NSString *name in [files.allKeys sortedArrayUsingSelector:@selector(compare:)])
        if (!write_file([staging stringByAppendingPathComponent:name], files[name])) {
            NSString *why = errno_text();
            [fm removeItemAtPath:staging error:nil];
            return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"The saves could not be written (%@: %@). Nothing was changed.%@", name, why, kept()]);
        }
    sync_dir(staging);
    if (renamex_np(staging.fileSystemRepresentation, target.fileSystemRepresentation, RENAME_SWAP)) {
        NSString *why = errno_text();
        [fm removeItemAtPath:staging error:nil];
        return fail(error, XCXSavesErrorWrite, [NSString stringWithFormat:@"The saves could not be replaced (%@). Nothing was changed.%@", why, kept()]);
    }
    sync_dir(target.stringByDeletingLastPathComponent);
    [fm removeItemAtPath:staging error:nil];   // now the old saves (and the backup holds them)
    if (backup) *backup = copy;
    if (folder) *folder = target;
    return YES;
}
