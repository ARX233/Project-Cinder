package com.wmmt.port;

import android.content.ContentResolver;
import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.UserPrincipal;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.SortedMap;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Read-only SAF input, not publication authority. Caller holds the Store ProcessLock
 * and supplies a Store.begin-minted job. Never writes job.json, seals, extracts,
 * publishes, authenticates a receipt, deletes partials, or changes a user document.
 *
 * Invoke on a background thread. Control offers best-effort source close and
 * CancellationSignal cancellation; a plain Cancel only polls between calls. A
 * provider/kernel which ignores cancellation or close can still block: this API
 * promises neither a hard deadline nor vendor-provider validation.
 */
public final class OriginalSourceBroker {
    private OriginalSourceBroker() { }

    /** Compressed archive limit, deliberately NOT the 2 GiB per-source-file limit. */
    public static final long MAX_ZIP_BYTES = 8L * 1024 * 1024 * 1024;
    public static final long FREE_SPACE_RESERVE = 64L * 1024 * 1024;
    public static final long MAX_SOURCE_BYTES = 2L * 1024 * 1024 * 1024;
    public static final long MAX_TOTAL_BYTES = 32L * 1024 * 1024 * 1024;
    public static final int MAX_CHILDREN = 16384;
    public static final int MAX_NAMESPACE = 65536;
    public static final int MAX_DEPTH = 64;
    public static final int MAX_WRAPPER_DEPTH = 8;
    public static final int MAX_WRAPPER_DIRECTORIES = 256;
    private static final int BUFFER_BYTES = 128 * 1024;
    private static final long MAIN_LENGTH = 24855892L;
    private static final String MAIN_SHA256 =
            "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6";
    private static final LinkOption[] NOFOLLOW = { LinkOption.NOFOLLOW_LINKS };
    private static final Set<PosixFilePermission> DIR_MODE = PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> FILE_MODE = PosixFilePermissions.fromString("rw-------");

    public interface Cancel { boolean cancelled(); }
    public interface Progress { void update(String stage, long current, long total); }

    public enum Code {
        CANCELLED, INVALID_JOB, INVALID_PROFILE, INVALID_METADATA, NO_ROOT,
        AMBIGUOUS_ROOT, SOURCE_MISSING, SIZE_MISMATCH, HASH_MISMATCH, LIMIT, SPACE
    }
    public static final class Failure extends IOException {
        private static final long serialVersionUID = 1L;
        public final Code code;
        Failure(Code code, String message) { super(message); this.code = code; }
    }

    /** One operation at a time; cancellation is permanent and never closes outputs. */
    public static final class Control implements Cancel {
        private final AtomicBoolean cancelled = new AtomicBoolean();
        private Operation active;
        @Override public boolean cancelled() { return cancelled.get(); }
        /** Returns promptly: potentially blocking provider close runs on a daemon. */
        public void cancel() {
            if (!cancelled.compareAndSet(false, true)) return;
            final List<Owned> snapshot;
            synchronized (this) {
                snapshot = active == null ? Collections.emptyList() : active.snapshot();
            }
            for (Owned resource : snapshot) {
                // At most a signal + cursor/source are live in the SAF adapter.
                // One uncooperative signal/close must not delay another owned FD close.
                // Each close is identity-bound and idempotent, never a raw FD number.
                Thread closer = new Thread(resource::closeQuietly, "OriginalSourceBroker-cancel");
                closer.setDaemon(true);
                closer.start();
            }
        }
        private synchronized void begin(Operation op) throws IOException {
            if (active != null) throw new IOException("Control is already in use");
            active = op;
        }
        private synchronized void end(Operation op) { if (active == op) active = null; }
    }

    public static final class CopiedFile {
        public final String path;
        public final long length;
        public final String sha256;
        /** fstat observation only; a nonregular provider stream is not a regular snapshot. */
        public final String sourceFdKind;
        CopiedFile(String path, long length, String sha256, String kind) {
            this.path = path; this.length = length; this.sha256 = sha256; this.sourceFdKind = kind;
        }
    }
    /** Immutable staging/provisional progress receipt; NEVER trusted publish authority. */
    public static final class Receipt {
        public final List<CopiedFile> files;
        public final long bytes;
        /** Always redacted; no document ID or user filesystem path is retained. */
        public final String rootUri;
        private Receipt(List<CopiedFile> files, long bytes) {
            this.files = Collections.unmodifiableList(new ArrayList<>(files));
            this.bytes = bytes;
            this.rootUri = "content://[redacted]";
        }
    }

    /**
     * Copies an opaque, at-most-8-GiB compressed archive to incoming.zip only.
     * No ZIP metadata is parsed here. UI MUST show MAX_ZIP_BYTES before selection.
     * PythonArchiveSource must subsequently verify all metadata/selected hashes.
     */
    public static Receipt copyZip(Context context, Uri uri, Path jobRoot,
                                  OriginalProfile profile, Cancel cancel, Progress progress)
            throws IOException {
        backgroundOnly();
        requireContent(uri);
        plan(profile); // Validate the audited profile even though ZIP bytes stay opaque here.
        JobArea area = JobArea.open(context.getNoBackupFilesDir().toPath(), jobRoot, profile.sha256);
        return copyZip(new SafProvider(context.getContentResolver(), uri, false), area,
                cancel, progress, SYSTEM_SPACE);
    }

    /** Copies the immutable APK-audited profile sources, then optional aura artwork. */
    public static Receipt copyTree(Context context, Uri tree, Path jobRoot,
                                   OriginalProfile profile, Cancel cancel, Progress progress)
            throws IOException {
        backgroundOnly();
        requireContent(tree);
        if (!DocumentsContract.isTreeUri(tree)) throw new IOException("A SAF tree URI is required");
        Plan plan = plan(profile);
        JobArea area = JobArea.open(context.getNoBackupFilesDir().toPath(), jobRoot, profile.sha256);
        return copyTree(new SafProvider(context.getContentResolver(), tree, true), area,
                plan, cancel, progress, SYSTEM_SPACE);
    }

    private static void backgroundOnly() throws IOException {
        if (Looper.myLooper() == Looper.getMainLooper())
            throw new IOException("SAF broker must run on a background thread");
    }
    private static void requireContent(Uri uri) throws IOException {
        if (uri == null || !"content".equals(uri.getScheme()))
            throw new IOException("Only read-only content URIs are accepted");
    }
    private static Failure fail(Code code, String message) { return new Failure(code, message); }

    // Package-private pure boundaries allow an external host harness, without a
    // fake Android runtime or exposing an alternate public production entrypoint.
    static final class Expected {
        final String path; final long length; final String sha256;
        Expected(String path, long length, String sha256) {
            this.path = path; this.length = length; this.sha256 = sha256;
        }
    }
    // Optional artwork is pinned separately so old sealed jobs and their primary profile stay valid.
    private static final List<Expected> AURA_SOURCES = Arrays.asList(
            new Expected("data/effect/car_aura_blue.igb",305263,"90b4357981687e4fe588dbcf5cfec6385637bae1b89fd7086e91d6cab83ddee1"),
            new Expected("data/effect/car_aura_glow_blue.igb",24707,"8d7c9903a4cd5bc90a482a3b34da8c4176a5c4c6d61207a5d6a9973e39825b8a"),
            new Expected("data/effect/car_aura_glow_green.igb",24708,"4764d76f6266f8a964c9025309d2afe2c59f4ee814d1d7db051c3599a64dc4fe"),
            new Expected("data/effect/car_aura_glow_purple.igb",24716,"4c5a024263485b4c657b79889d6d0731c864ce5c0268211aca7791426fdfd274"),
            new Expected("data/effect/car_aura_glow_red.igb",24706,"da64fddf97f044ec78b15c1dce320511f8a2bb1f92c403b284fc54c487f97dd2"),
            new Expected("data/effect/car_aura_green.igb",305266,"7f197cba7d06833efcdc7a1e40ada449710ed2a8b9b519e39c625cf88be42d86"),
            new Expected("data/effect/car_aura_purple.igb",305283,"90c13e5978a4d818ac5147ac9d231708f63a2048b883fb75df4c6b5344256b32"),
            new Expected("data/effect/car_aura_red.igb",305260,"a5fa7cec21222fd3bcf5357358211880aee3e09e03d9ace9be2d50d2050cfcae"));

    private static final List<Expected> FINISH_MENU_SOURCES = Arrays.asList(
            new Expected("data/anime/cons_g_last_000m.anm",37032,"d4c4dd94aae0c965c3d98e3d06dd8c6543aadced1a71706cdf322024299d3937"),
            new Expected("data/anime/cons_g_last_saigo.anm",8232,"10bf2126e10a037068d4650831e1a02c23da9c62e7204aaa72f0393cff93ebb3"),
            new Expected("data/anime/cons_g_last_tonikaku.anm",12072,"032ce768c040d09fc7e00922dc8758e98e9f5887cc313af07d63dc59cbb30e8d"),
            new Expected("data/sprite/cons_p_finish_rival.png",2761,"8ac9082082c54d6d74dc213f8d17f7a525a6fe35d9315590245c3d5edaed7d00"),
            new Expected("data/sprite/cons_p_finish_saigo.png",7533,"10d4b7d5e9ccf77ae2422cf6bb2dbc6f3c9ba59ab98205116bf006683e827af3"),
            new Expected("data/sprite/cons_p_finish_tonikaku.png",6525,"0b05141db5187ecc93ad71df2ca072583f976d6b0087ad576ff86113b4012b63"),
            new Expected("data/sprite/cons_p_last_0_template.png",2872,"27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c"),
            new Expected("data/sprite/cons_p_last_1_template.png",2872,"27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c"),
            new Expected("data/sprite/cons_p_last_2_template.png",2872,"27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c"),
            new Expected("data/sprite/cons_p_last_m.png",3613,"c2193f52f59a5a473f80216b14825f9d60ca57b1ad2147f4dbc5408a34d4274c"),
            new Expected("data/sprite/cons_p_last_m_template.png",242,"b9d795a35e3971223a7315b664c3bb9887b3c945da9eb446e48bf4c5b9ac7483"));

    private static final List<Expected> CROWN_SCENE_SOURCES = Arrays.asList(
            new Expected("data/anime/menu_g_cardcheck_5_point.anm",12072,"834ecd8402ace85984bf3e13af13108d8c46f6552193c436f60d0a65ba5cadce"),
            new Expected("data/anime/menu_g_cardcheck_5_waku.anm",208,"25bc0ebc367800e1ace9b37bb64f697eff33135fd75cfa6247439eb2a2e49d85"),
            new Expected("data/anime/menu_g_crown_atract.anm",64872,"eea2cad0206610a3dc6ac83a220919707a311041914ba8db000111b5390da75d"),
            new Expected("data/anime/menu_g_crown_atract_title.anm",13672,"c275b90c0e4c62f381248371630402b9543a00c5b4e5158ea1c610bc14bcbfa6"),
            new Expected("data/anime/menu_g_crown_bg.anm",144,"a90f42e5383860c868d69fa84dfd8354eb04a2a99dbccd02fc045c7884b09dc9"),
            new Expected("data/anime/menu_g_crown_get_title.anm",8136,"bc7af4c6c615ca98dd9366984314782c39e99b6d00fa09949d39eb0ecee29b27"),
            new Expected("data/anime/menu_g_crown_waku.anm",592,"4311c7d6c0469d58a0714839d049085ae1b91f9a7b0bb051522671dee5951053"),
            new Expected("data/anime/menu_layout_cardcheck_5.anm",720,"a81fc10b4490c8ed49d9b27cc240a2a7b06e893d52b5ae49acd8a0e8ea62d3f2"),
            new Expected("data/anime/menu_layout_crown_get_a.anm",12616,"2995f2ed2eb9ee93a5a168b62f9a0e4644bf6b241d9bf376264d69b6cbcd1b5d"),
            new Expected("data/anime/menu_layout_crown_get_b.anm",45384,"440b607051210415b095ee7ff0be3265efff020db3ab406016cd156d475b1eaf"),
            new Expected("data/anime/menu_layout_crown_saikyo.anm",11112,"cdbb19cf16e2e41b643622166e7c8b32885585da0b925c296a748943f6b2c8e3"),
            new Expected("data/anime/menu_layout_crown_saikyo_all.anm",15744,"a2d0b532e4e0f4a3543d898f9c623595737f83139236f7cc649c7b4452b178c0"),
            new Expected("data/sprite/font_28_black_1.png",630259,"68153bbc2dfe28e69627a6d085994ad93b1c730dbe3dd17168c2d529c92894ed"),
            new Expected("data/sprite/menu_p_card_14_battle_sen.png",3684,"2113f7237a240256cd4b261742cac1cf3ed5ae04629377005e076b04672fc364"),
            new Expected("data/sprite/menu_p_card_5_graph.png",88650,"d7d53a8c7141ea3517ab86f67b4260c044ab28099878bf9e6ff7267876fed273"),
            new Expected("data/sprite/menu_p_card_5_menu.png",4589,"caca7930e071411c4db46f99e788dc9336de1e000e81c7f952acd03303196575"),
            new Expected("data/sprite/menu_p_card_5_point_1.png",3024,"3335cd2e10c36ea957a69ef0861f68b134933a5cede6def397d40330f191aa27"),
            new Expected("data/sprite/menu_p_card_5_point_2.png",2949,"d015924c7e757cb14ec952e78364a585edd739a72d16f3c1a90373c64695c7c1"),
            new Expected("data/sprite/menu_p_card_5_point_3.png",3291,"c3831a18aac03af01d80ea93de417d2bba4d86600b7a5986b6bc6d8927040f81"),
            new Expected("data/sprite/menu_p_card_5_title.png",7687,"9a8041b5b3d91df837f5244c3bd03529fc832ff571c0fb465cd85aaab20e9626"),
            new Expected("data/sprite/menu_p_card_waku_1.png",34641,"2af996167cb492884a65f9e0a219b7bf626eca39c5f4e6e071ea5281857b56b7"),
            new Expected("data/sprite/menu_p_crown_L_C1.png",84861,"8fed58e3ce85a04803b751b24b860a693734b6cb6e369ed3db8253c6d3e2f58a"),
            new Expected("data/sprite/menu_p_crown_L_fk.png",60749,"2cbc6e70166c0180b647010e1e905f67b6a830b6c7e39eaf7d142b814ad4aaff"),
            new Expected("data/sprite/menu_p_crown_L_hk.png",85101,"c3a033c86411449e3445fc3d51db6a91528e9fa1d2740695f7c4db1a3783156e"),
            new Expected("data/sprite/menu_p_crown_L_ng.png",88877,"a4bcd3a1d6ebf8a7a70c5091d52c9745fa7c96d17bc890f24e632210dc6a06fd"),
            new Expected("data/sprite/menu_p_crown_L_os.png",81838,"7cb42837f25c049742f2d0d5ed77e1a8cfd9dbb0da1210d77167d0192c539ca2"),
            new Expected("data/sprite/menu_p_crown_L_sk.png",86648,"58946640f43626ac1684b8c786f75b7e58c92796e75cf830873867b04d40ad3c"),
            new Expected("data/sprite/menu_p_crown_L_wg.png",89671,"75b251fdf1c12d783dd1abe3b6661854113ff0995125bb51f2a0b1bf8a50f3fa"),
            new Expected("data/sprite/menu_p_crown_L_yk.png",88340,"1c4e8a8f887f7262173be7f80370eada9ec80a52c7def35ffb161e4e8f65c04b"),
            new Expected("data/sprite/menu_p_crown_S_C1.png",16208,"0bf6b01b52b0a37f5aa2d5aedddc17927e6d4e3e17445cda4d79e1dda1b92029"),
            new Expected("data/sprite/menu_p_crown_S_fk.png",13016,"c31883970849062b2fad5fdec57e2770a5d2c58255128aebc674f5325a667644"),
            new Expected("data/sprite/menu_p_crown_S_hk.png",17058,"d75125790265acc1482bcbd6a43b678fba79c980fbb9a5e2a1d2b89de6c19d74"),
            new Expected("data/sprite/menu_p_crown_S_ng.png",17604,"f7619f54bc42479067fae0fb6322a1db8adc2144c1426abb1216f2314f4642f7"),
            new Expected("data/sprite/menu_p_crown_S_os.png",15747,"713f7669233f93bdfe6914f111ded3618267e043d3b29aaa9561a383e79cb242"),
            new Expected("data/sprite/menu_p_crown_S_sk.png",11900,"0d0596549ebbf9e34b689b249d6d4c8e09e621197f003e53ef8fdd6db6fe4156"),
            new Expected("data/sprite/menu_p_crown_S_waku_C1.png",14804,"f6e7945460d74aec56636d9f502301adec4bd2f1aacac9e59ba5e2c7eef4e857"),
            new Expected("data/sprite/menu_p_crown_S_waku_fk.png",12104,"877cff2a884b11fc09c4c16734d1d7c8a4818f6cd2fc48fa12b272f5402d66ea"),
            new Expected("data/sprite/menu_p_crown_S_waku_hk.png",15803,"6f412a7736a10b7ca8c56e443e6061d2a25f51a2b95b85efe66d6367bd957ffb"),
            new Expected("data/sprite/menu_p_crown_S_waku_ng.png",16599,"39dd4baa96ce2ed05637887916fe9f6153bf25b0c6ef5f11b05820c71071c2db"),
            new Expected("data/sprite/menu_p_crown_S_waku_os.png",14399,"cb0a46aacd6cb2a920615b739cbeb1e0bd331cc6a59e400e95db9a5ef55a8185"),
            new Expected("data/sprite/menu_p_crown_S_waku_sk.png",11337,"be77cc2d0d119926e469356594f3492b6179d138973ff7d849bc378d38ffec08"),
            new Expected("data/sprite/menu_p_crown_S_waku_wg.png",12965,"e43fc164f31d88a54982a20f21ee46b2488b6bbfcadcd5cadbcc5805e9439db3"),
            new Expected("data/sprite/menu_p_crown_S_waku_yk.png",14961,"4988f795b7baea47fc6b3ca0cf51169c51d08674ed1d361be82f3a95af48858b"),
            new Expected("data/sprite/menu_p_crown_S_wg.png",14204,"69eaa6236da23e2a5d9dc3c4b2b2bfcd717a5c36d8b24bf5310c15104f93e37d"),
            new Expected("data/sprite/menu_p_crown_S_yk.png",17277,"857fbfba604d5e48aba52deecde68bc4b0db6dbfea3c4439543a09fd87ff89a9"),
            new Expected("data/sprite/menu_p_crown_atract_c1.png",62498,"ed001430bcb3167c318373950f86ed111682bbb6e8e8d4de53361f50f16d4779"),
            new Expected("data/sprite/menu_p_crown_atract_fk.png",44136,"92c35817e1c98c44bfda541da88ee3be3528b8a8dfd6c7b310e8d0bfb5aa4ee2"),
            new Expected("data/sprite/menu_p_crown_atract_gray.png",172977,"c4c9c02a907467410874e66d8029cc31ed75545be067d2d8e092b98b115aaaf1"),
            new Expected("data/sprite/menu_p_crown_atract_hk.png",61432,"003444cdd4cafb3fcebfb715ed6fb234391aba232e85bbc89ec7fb2f85d05183"),
            new Expected("data/sprite/menu_p_crown_atract_ng.png",40538,"126b6e08c82dbf252a461a05afabf572ca56e7d3f744c8dad56f8fd77aec8c9a"),
            new Expected("data/sprite/menu_p_crown_atract_os.png",43675,"00dbd14761d73fd98c87706c4c63d03ba72f82915ea18827029d2c923fa74f02"),
            new Expected("data/sprite/menu_p_crown_atract_sk.png",50868,"fb4bc884f9b039b5366bf6083093b3a2219344ded9a77cf3b5cb0ba1865f52ac"),
            new Expected("data/sprite/menu_p_crown_atract_title_ghost.png",7059,"041de08371a0c2d3ef6cab6a9c593ebb966dacef899035767d2eb03e993cb697"),
            new Expected("data/sprite/menu_p_crown_atract_title_saikyo.png",15373,"0a4abfbffa8bc1eddf95a19a51161a20c55ad5c1545f9edd8f69ced11f0e0dbd"),
            new Expected("data/sprite/menu_p_crown_atract_wg.png",45812,"ccc0934981eb167e4c98b61d788aba4fec114b167c35002eaf868cbd134f2365"),
            new Expected("data/sprite/menu_p_crown_atract_yk.png",43597,"9bb9d8e0cd50028fd14ce29015a44ff00d401754823dffdb825a31a366ec5ff8"),
            new Expected("data/sprite/menu_p_crown_bg.png",3747,"73243779311ca3a8247835943051d25f30e73df8cb9c7f690d82832a64b9e0c7"),
            new Expected("data/sprite/menu_p_crown_mes.png",40227,"6e37d314001a74eea434e72a7ace2e9f6dfc33cf32d283298377d9ace78dbb49"),
            new Expected("data/sprite/menu_p_crown_mes_C1.png",26124,"1617b75440ccd21ed3d7170efa956422aadf87aac1dd64a942319f5907c5926e"),
            new Expected("data/sprite/menu_p_crown_mes_all.png",42185,"73888c0dd3802ea0d8191ba7235b1a767dd96b5ae7b28fd3193d6fb71ad57be7"),
            new Expected("data/sprite/menu_p_crown_mes_fk.tga",262188,"67200d0abb2b1c34246909a4d40268d3a30d97076132f509da6dcc7b5e9b2bd4"),
            new Expected("data/sprite/menu_p_crown_mes_hk.png",34982,"9ff7bf1c9bd0ce6bb2cc5aaefcf8aa22e778f146084a573cd2663d463e1537a0"),
            new Expected("data/sprite/menu_p_crown_mes_ng.png",35575,"24ebac2b41be848ce6ad0a8fd099f50059abc361755d9e124799e660fab14f80"),
            new Expected("data/sprite/menu_p_crown_mes_os.png",32882,"79e8d327620a2b01df06d065ebf5fcfae0c393cda2c2fa52c00095d1d9804bff"),
            new Expected("data/sprite/menu_p_crown_mes_sk.png",42060,"7ef6d8abab032dac1f3d128d26b2e4b5b4abe9bbcd8f0637852b06358e303022"),
            new Expected("data/sprite/menu_p_crown_mes_wg.png",41825,"356b006c1cc6fbb2271cd8d8c8ac3efc02a01ecd59c2ef1a7c58495be8f9d170"),
            new Expected("data/sprite/menu_p_crown_mes_yk.png",44689,"916d09bfe0b2424b481df4b363d8dfdbd72969d826ae59ab71801debf58065f8"),
            new Expected("data/sprite/menu_p_crown_title.png",22930,"c252b5f6fcee25adf4e9ccc0b04c72259363c14ed72453844fca24dbc57a8e3a"),
            new Expected("data/sprite/menu_p_flash.png",205925,"11b80aeab5e35a6e126fe7bb00c46ae1c373cd2a8823803515c642eccbbbe7bc"),
            new Expected("data/sprite/menu_p_topbar_mes_cardcheck_6.png",30419,"a5a2b43cd381430ea1d30901471e72b33e874df4fa6090c522aef911bd87b260"));

    private static final List<Expected> TEN_BGM_SOURCES = Arrays.asList(
            new Expected("data/sound/bgm/maxi3/ten_a1.wav",3072044,"b197e2d96b950606aa24bcad3504ef99243173959fc3e43925a65c7afde801ae"),
            new Expected("data/sound/bgm/maxi3/ten_a2.wav",1536044,"4831a337bbc8c5cfb9d035073263ffb95ad653c0f5612f6243dafbca5b1702bf"),
            new Expected("data/sound/bgm/maxi3/ten_a3.wav",1536044,"90486780618e00fbd953dc4e4cd8e63358857ff401a032a42dd74c3ff99ead45"),
            new Expected("data/sound/bgm/maxi3/ten_a4.wav",1536044,"94a0b6512f55b2a4bd29ab371d55c5b3cb1d1d958829b656cf1ef588ec7b6af0"),
            new Expected("data/sound/bgm/maxi3/ten_a5.wav",1536044,"568025c0088c6c58f04864159355d4baa64651de5be904141267bd1f288cfc55"),
            new Expected("data/sound/bgm/maxi3/ten_a6.wav",1536044,"f77eb6fe5b33f6857ecbcc9f6227413ced76cadb4cdaf7125cd9be37c96916fa"),
            new Expected("data/sound/bgm/maxi3/ten_a7.wav",3072044,"f245b09fa3e23c6bc3c12ccca2ad0c93bf7d2c417097b12acd321b4a0c8b8c7e"),
            new Expected("data/sound/bgm/maxi3/ten_a8.wav",3264044,"88fa4b32044e41a2a21315ce3f3476851a5f58e78ab7fae5ee878ae6c717338b"),
            new Expected("data/sound/bgm/maxi3/ten_a9.wav",6144044,"073818bd1aa76b80a983b9bc869ccdef263d57cf72a5b01a9460e3bfbf70c409"),
            new Expected("data/sound/bgm/maxi3/ten_b1.wav",1536044,"cf2381d42c568c77f10fb4e16ca1166a831f4095782b5c0e3488446d6ca2b6ae"),
            new Expected("data/sound/bgm/maxi3/ten_b2.wav",1536044,"341c1f0e95a3d0664708727c7e48a94ae0b7b6a32a41107cf540d8902d113b3c"),
            new Expected("data/sound/bgm/maxi3/ten_b3.wav",1536044,"63cbfd16c7b3bbffee69043c7fb144ed521eeecfa1e959ef47ac19a3f707a32b"),
            new Expected("data/sound/bgm/maxi3/ten_b4.wav",1536044,"df0b12c910538e2a53736594096956570480a540cde44b22ddd7303ee0332d7b"),
            new Expected("data/sound/bgm/maxi3/ten_b5.wav",1536044,"320966c7c32d414f7521f27968f480ed839e3f630fd1c78347dfaff7c0b9f660"),
            new Expected("data/sound/bgm/maxi3/ten_b6.wav",3072044,"2d4ef4cc8d572ee4ee0d12548da89f6e7c0a9303e84f7f8803dd42eeb5de75b3"),
            new Expected("data/sound/bgm/maxi3/ten_b7.wav",3072044,"f837529c2da573358173c325481133196da5e2065f10f2b4b3d135c904054507"),
            new Expected("data/sound/bgm/maxi3/ten_b8.wav",6144044,"0f292a0a89287e95c21b4ac4ad4ec3d1f0fff54aeb553ba9a6f245fc75f92cd3"),
            new Expected("data/sound/bgm/maxi3/ten_c1.wav",3072044,"d9ba5fb2f37a7d02f758a4219fd15bf76ad6c1eb105ce5746bed4af97a1ec105"),
            new Expected("data/sound/bgm/maxi3/ten_c2.wav",3072044,"8eb9ad2523ec64b2c3ed1103bbd6cb239f7e5babc6ad58e6cb0638f15e414877"),
            new Expected("data/sound/bgm/maxi3/ten_c3.wav",6144044,"6072cea9aef743fbcb3dd8e7bf40d47e53eefdb1a106930a0047a04b880931b8"),
            new Expected("data/sound/bgm/maxi3/ten_c4.wav",6144044,"da31e40c87156e3404a4daac3eb57364316de64dccc4c5ed0585c4ccf16984f7"),
            new Expected("data/sound/bgm/maxi3/ten_c5.wav",6144044,"833af7edc278213428108136e77deac5596ee4eaac13256b7d8007f7c7063fc4"),
            new Expected("data/sound/bgm/maxi3/ten_c6.wav",3840044,"a70bb6b17ab910f9af8b15d5a69a9ce718e46d51a5b4f5e8b89f24ea90426004"),
            new Expected("data/sound/bgm/maxi3/ten_c7.wav",3072044,"b11b47b6a4b25c8c1699d748e0e1070ce48b019ee9eed0ce98b891ecfeba2405"),
            new Expected("data/sound/bgm/maxi3/ten_c8.wav",4608044,"2b8fd09d851c7391cf3f1406f4a3746daef9acb322217161e6f67c8b2ea8778d"),
            new Expected("data/sound/bgm/maxi3/ten_d1.wav",4736940,"86feb990533102f15ab2fdd383fd396dd6411e0a50ddd1ee420b1c0327f39229"),
            new Expected("data/sound/bgm/maxi3/ten_d2.wav",9473836,"f505e53384c8ad4b1b72b88a18cf56041ba513c8b59ca40ddf8e172fc6bdf5ab"),
            new Expected("data/sound/bgm/maxi3/ten_d3.wav",4736944,"9cebe46eab910aa828aa4650bea705df65cd47f0412bffce6339d15289c88241"),
            new Expected("data/sound/bgm/maxi3/ten_d4.wav",9473836,"bc7c9d6fc1a7e8185db40fe8e84dd8bd045ce039aef17c5b66f7338ad835228c"),
            new Expected("data/sound/bgm/maxi3/ten_d5.wav",5329052,"92c35c0f010be4d55c456ea580d9f4c0c96d6174e1609c02c70b029c13ea590e"),
            new Expected("data/sound/bgm/maxi3/ten_d6.wav",9473836,"6c611e3993f42245197eac01d4b551df9d42824579cce14613a791bbcd2203b9"),
            new Expected("data/sound/bgm/maxi3/ten_e1.wav",4736940,"ae6d2a32e877be2685db7a2bce539da68905437dc10f074cd8df3ebd7fca4bb9"),
            new Expected("data/sound/bgm/maxi3/ten_e2.wav",4736940,"ac693740ceaf70abe2d4c03644fc93bc887ec6fffc61aa9dc89a6d4672bd691a"),
            new Expected("data/sound/bgm/maxi3/ten_e3.wav",7105388,"f366d30c6344e769a3d647cc3c97defd045b0538f9426d1e85a1f9048d7110e5"),
            new Expected("data/sound/bgm/maxi3/ten_e4.wav",4736940,"3fd96d0d200047feaa6cb81caa694cd270741d21b5938f79302d76ef9a2a9485"),
            new Expected("data/sound/bgm/maxi3/ten_e5.wav",4736940,"cb3672a112ecb927d2cdf9c2fbaeeb4939abc8c749c6803d7f695d9840219cbf"),
            new Expected("data/sound/bgm/maxi3/ten_e6.wav",2368492,"21be37f752afe3f693438dae0ee6ee363afbe26a2962021a1e00cdc5642a55aa"),
            new Expected("data/sound/bgm/maxi3/ten_e7.wav",8289616,"0cdb097cd06544550d6c294fd3735791165594f0ae19eff2fd0cc14c16f65806"));

    private static final List<Expected> GHOST_WHEEL_SOURCES = Arrays.asList(
            new Expected("data/changewheel/gem_lman/lman_mid.igb",306825,"31df4c9e831196bc685cdd882053707a1f0e9c2f55c6f1426da6f92f134d1798"),
            new Expected("data/changewheel/gem_lman/lman_mid_col1.tga",786476,"780ed1904457a6fb483745736eb4a681671c1755373f92fc545174131e3b454f"));

    private static final List<Expected> GHOST_MATCH_SOURCES = Arrays.asList(
            new Expected("data/sprite/menu_p_crown_L_C1.png",84861,"8fed58e3ce85a04803b751b24b860a693734b6cb6e369ed3db8253c6d3e2f58a"),
            new Expected("data/sprite/menu_p_crown_L_fk.png",60749,"2cbc6e70166c0180b647010e1e905f67b6a830b6c7e39eaf7d142b814ad4aaff"),
            new Expected("data/sprite/menu_p_crown_L_hk.png",85101,"c3a033c86411449e3445fc3d51db6a91528e9fa1d2740695f7c4db1a3783156e"),
            new Expected("data/sprite/menu_p_crown_L_ng.png",88877,"a4bcd3a1d6ebf8a7a70c5091d52c9745fa7c96d17bc890f24e632210dc6a06fd"),
            new Expected("data/sprite/menu_p_crown_L_os.png",81838,"7cb42837f25c049742f2d0d5ed77e1a8cfd9dbb0da1210d77167d0192c539ca2"),
            new Expected("data/sprite/menu_p_crown_L_sk.png",86648,"58946640f43626ac1684b8c786f75b7e58c92796e75cf830873867b04d40ad3c"),
            new Expected("data/sprite/menu_p_crown_L_wg.png",89671,"75b251fdf1c12d783dd1abe3b6661854113ff0995125bb51f2a0b1bf8a50f3fa"),
            new Expected("data/sprite/menu_p_crown_L_yk.png",88340,"1c4e8a8f887f7262173be7f80370eada9ec80a52c7def35ffb161e4e8f65c04b"),
            new Expected("data/sprite/menu_p_car1_waku_w_2.png",4043,"ed42cf68ca42bf590cf2a7525a584ce807b8bc3159e800fea55928a77f2415c6"),
            new Expected("data/sprite/menu_p_pre_tg_rival_great.png",11811,"40fdd4ef933278508b4a3720e707983f01fae1e4e324c5e053beca7e5c7a4c39"));

    private static final List<Expected> MILEAGE_MENU_SOURCES = Arrays.asList(
            new Expected("data/anime/menu_layout_milage.anm",100392,"98f38619f40def58335c863e78be0c33e80144f21df982d61d049293d7f2ce77"),
            new Expected("data/sprite/menu_p_milage_0.png",4149,"6733e3a9b37904ba04c6573fbb460af0a1d68f9143aa4b31d9dfe4ba1b37a5b9"),
            new Expected("data/sprite/menu_p_milage_1.png",3705,"b2803157ac3847ec36919d6c6fac6396b3c4708015a8267e1f681f4acfa431ed"),
            new Expected("data/sprite/menu_p_milage_2.png",4138,"0940fb1f57dbe962b16833234dec93fd08c40b8d780c5530879d4f7e3be9ef99"),
            new Expected("data/sprite/menu_p_milage_3.png",4177,"cf6f92bbca4b24a0ef1b5975797c2a2083ffebf6261de758d208f91fac4c7717"),
            new Expected("data/sprite/menu_p_milage_4.png",4046,"80469e1ea598db093d3d68b94afde68371a36770cce3d2cbffae02c42b4eb77c"),
            new Expected("data/sprite/menu_p_milage_5.png",4033,"ce36fbf11d99622a65ae4782a5455a99f875f582eaa0efd183471728009e3477"),
            new Expected("data/sprite/menu_p_milage_6.png",4110,"1fff1f03f996dbb62dfc8bceae98fa63a6a6f075019259848a8581d92be9e091"),
            new Expected("data/sprite/menu_p_milage_7.png",3836,"68b1abe5a87a31db2a481ae75316de59e40a286b13c6aaeca99f5c4182c8ae4f"),
            new Expected("data/sprite/menu_p_milage_8.png",4116,"287ab45cc0b3ca24c581c5187a87662918d05948dc239b14c33b5845d2b4b917"),
            new Expected("data/sprite/menu_p_milage_9.png",4094,"e8d64ea7a02ed2bccdaa2adb011a24ee61767134cc35edbfb14a3641a9c4dacd"),
            new Expected("data/sprite/menu_p_milage_a.png",4336,"6deeb84dd727a0816fefd40ed05e538e7ac4c2e63cd53032f1ed4b8994c120fc"),
            new Expected("data/sprite/menu_p_milage_bg.png",59459,"d9cda4719d3442c7c09358d7559cb7c4f113035e9bd577402a5c1f433bfdb763"),
            new Expected("data/sprite/menu_p_milage_comma.png",3444,"cbbd3dd56caabb3039aeb5427030c42715c4466e05524a6b07aa50a49ec86c3e"),
            new Expected("data/sprite/menu_p_milage_km.png",4566,"204ced5c1b974c26268cfb0f794a9199223b9525bacfed16a4c6a199715c9685"));

    static final class Plan {
        final List<Expected> files; final long bytes;
        Plan(List<Expected> sources) throws IOException {
            if (sources == null || sources.isEmpty() || sources.size() > MAX_NAMESPACE)
                throw fail(Code.INVALID_PROFILE, "Invalid source inventory");
            List<Expected> ordered = new ArrayList<>(sources);
            Map<String, String> caseless = new HashMap<>();
            Set<String> exact = new HashSet<>();
            long total = 0;
            for (Expected source : ordered) {
                if (source == null || source.length < 0 || source.length > MAX_SOURCE_BYTES
                        || !hex64(source.sha256)) throw fail(Code.INVALID_PROFILE, "Invalid source entry");
                validateRelative(source.path);
                if (!source.path.equals("main") && !source.path.startsWith("data/"))
                    throw fail(Code.INVALID_PROFILE, "Source must be main or below data");
                if (!exact.add(source.path)) throw fail(Code.INVALID_PROFILE, "Duplicate source path");
                String old = caseless.putIfAbsent(fold(source.path), source.path);
                if (old != null) throw fail(Code.INVALID_PROFILE, "Caseless source path alias");
                total = Math.addExact(total, source.length);
                if (total > MAX_TOTAL_BYTES) throw fail(Code.INVALID_PROFILE, "Source total exceeds 32 GiB");
            }
            if (!exact.contains("main")) throw fail(Code.INVALID_PROFILE, "Missing audited main");
            Map<String, String> allPrefixes = new HashMap<>(caseless);
            for (String path : exact) {
                int slash = path.indexOf('/');
                while (slash >= 0) {
                    String prefix = path.substring(0, slash), folded = fold(prefix);
                    if (caseless.containsKey(folded))
                        throw fail(Code.INVALID_PROFILE, "Source file/directory conflict");
                    String previous = allPrefixes.putIfAbsent(folded, prefix);
                    if (previous != null && !previous.equals(prefix))
                        throw fail(Code.INVALID_PROFILE, "Caseless source directory alias");
                    if (allPrefixes.size() > MAX_NAMESPACE)
                        throw fail(Code.INVALID_PROFILE, "Source paths exceed namespace budget");
                    slash = path.indexOf('/', slash + 1);
                }
            }
            // TreeMap order alone is insufficient: main is explicitly FIRST.
            ordered.sort(Comparator.comparing((Expected s) -> !s.path.equals("main"))
                    .thenComparing(s -> s.path));
            this.files = Collections.unmodifiableList(ordered); this.bytes = total;
        }
    }
    static Plan plan(OriginalProfile profile) throws IOException {
        if (profile == null || !hex64(profile.sha256) || profile.sources == null)
            throw fail(Code.INVALID_PROFILE, "Missing immutable profile");
        SortedMap<String, OriginalProfile.Source> sources = profile.sources;
        if (sources.size() > MAX_NAMESPACE)
            throw fail(Code.INVALID_PROFILE, "Source inventory exceeds namespace budget");
        List<Expected> entries = new ArrayList<>();
        for (Map.Entry<String, OriginalProfile.Source> entry : sources.entrySet()) {
            OriginalProfile.Source s = entry.getValue();
            if (s == null || entry.getKey() == null || !entry.getKey().equals(s.path))
                throw fail(Code.INVALID_PROFILE, "Source map key differs from path");
            entries.add(new Expected(s.path, s.length, s.sha256));
        }
        Plan result = new Plan(entries);
        Expected main = result.files.get(0);
        if (main.length != MAIN_LENGTH || !MAIN_SHA256.equals(main.sha256))
            throw fail(Code.INVALID_PROFILE, "Not the audited Android 1.35 main");
        if (profile.sourceBytes != result.bytes)
            throw fail(Code.INVALID_PROFILE, "Profile source byte total mismatch");
        return result;
    }
    private static boolean hex64(String value) { return value != null && value.matches("[0-9a-f]{64}"); }

    static void validateRelative(String path) throws IOException {
        if (path == null || path.isEmpty() || path.startsWith("/") || path.endsWith("/"))
            throw fail(Code.INVALID_METADATA, "Invalid relative source path");
        String[] segments = path.split("/", -1);
        if (segments.length > MAX_DEPTH) throw fail(Code.LIMIT, "Source path exceeds depth 64");
        for (String segment : segments) validateName(segment);
    }
    static void validateName(String name) throws IOException {
        if (name == null || name.isEmpty() || name.length() > 1024
                || !Normalizer.isNormalized(name, Normalizer.Form.NFC)
                || name.equals(".") || name.equals("..") || name.endsWith(".") || name.endsWith(" "))
            throw fail(Code.INVALID_METADATA, "Unsafe or non-NFC document name");
        for (int i = 0; i < name.length();) {
            int cp = name.codePointAt(i);
            int type = Character.getType(cp);
            if (cp == '/' || cp == '\\' || cp == ':' || Character.isISOControl(cp)
                    || type == Character.FORMAT || type == Character.SURROGATE
                    || type == Character.LINE_SEPARATOR || type == Character.PARAGRAPH_SEPARATOR)
                throw fail(Code.INVALID_METADATA, "Unsafe document name character");
            i += Character.charCount(cp);
        }
    }
    // Bounded conservative key, NOT a complete Unicode CaseFold implementation.
    // Stabilization covers multi-round expansions such as ẞ -> ß -> ss;
    // additional aliases may be rejected. Never uses the default locale.
    static String fold(String name) throws IOException {
        String current = Normalizer.normalize(name, Normalizer.Form.NFC);
        for (int round = 0; round < 4; round++) {
            String next = Normalizer.normalize(
                    current.toUpperCase(Locale.ROOT).toLowerCase(Locale.ROOT), Normalizer.Form.NFC);
            if (next.equals(current)) return current;
            current = next;
        }
        throw fail(Code.INVALID_METADATA, "Caseless name did not stabilize within four rounds");
    }

    static final class Document {
        final String id, name; final boolean directory, virtual; final Long size;
        Document(String id, String name, boolean directory, boolean virtual, Long size) {
            this.id = id; this.name = name; this.directory = directory; this.virtual = virtual; this.size = size;
        }
    }
    interface Provider {
        Document root(Operation operation) throws IOException;
        List<Document> children(Document directory, Operation operation) throws IOException;
        ReadHandle open(Document document, Operation operation) throws IOException;
    }
    static class ReadHandle implements Closeable {
        private InputStream input;
        final String fdKind;
        private Closeable descriptor;
        private boolean closed;
        ReadHandle(InputStream input, String kind) { this.input = input; this.fdKind = kind; }
        ReadHandle(Closeable descriptor, String kind) { this.descriptor = descriptor; this.fdKind = kind; }
        synchronized void attach(InputStream stream) throws IOException {
            if (closed) { stream.close(); throw fail(Code.CANCELLED, "Source closed during open"); }
            input = stream;
        }
        synchronized InputStream input() throws IOException {
            if (closed || input == null) throw fail(Code.CANCELLED, "Source handle closed");
            return input;
        }
        @Override public void close() throws IOException {
            final InputStream stream; final Closeable fd;
            synchronized (this) {
                if (closed) return;
                closed = true; stream = input; fd = descriptor;
            }
            IOException error = null;
            // Close the descriptor first: do not wait for InputStream's monitor
            // while its read may be blocked. Neither handle belongs to the caller.
            if (fd != null) try { fd.close(); } catch (IOException e) { error = e; }
            if (stream != null) try { stream.close(); } catch (IOException e) {
                if (error == null) error = e; else error.addSuppressed(e);
            }
            if (error != null) throw error;
        }
    }
    private static final class Owned implements Closeable {
        final Closeable resource; final AtomicBoolean closed = new AtomicBoolean();
        Owned(Closeable resource) { this.resource = resource; }
        @Override public void close() throws IOException {
            if (closed.compareAndSet(false, true)) resource.close();
        }
        void closeQuietly() { try { close(); } catch (IOException | RuntimeException ignored) { } }
    }
    static final class Operation implements Closeable {
        final Cancel cancel;
        final Map<Closeable, Owned> owned = new IdentityHashMap<>();
        Operation(Cancel cancel) throws IOException {
            this.cancel = cancel == null ? () -> false : cancel;
            if (this.cancel instanceof Control) ((Control) this.cancel).begin(this);
            try { check(); } catch (IOException e) { close(); throw e; }
        }
        void check() throws IOException {
            if (cancel.cancelled()) throw fail(Code.CANCELLED, "Source copy cancelled; partial remains private");
        }
        Owned track(Closeable source) throws IOException {
            Owned result;
            synchronized (this) { result = owned.computeIfAbsent(source, Owned::new); }
            if (cancel.cancelled()) { result.closeQuietly(); check(); }
            return result;
        }
        void release(Closeable source) throws IOException {
            Owned value;
            synchronized (this) { value = owned.remove(source); }
            if (value != null) value.close();
        }
        void forget(Closeable source) { synchronized (this) { owned.remove(source); } }
        synchronized List<Owned> snapshot() { return new ArrayList<>(owned.values()); }
        @Override public void close() {
            for (Owned resource : snapshot()) resource.closeQuietly();
            synchronized (this) { owned.clear(); }
            if (cancel instanceof Control) ((Control) cancel).end(this);
        }
    }

    static final class Listing {
        final Map<String, Document> exact;
        Listing(List<Document> rows) throws IOException {
            if (rows == null || rows.size() > MAX_CHILDREN)
                throw fail(Code.LIMIT, "Directory exceeds 16384 rows");
            Map<String, Document> names = new LinkedHashMap<>();
            Set<String> keys = new HashSet<>(), ids = new HashSet<>();
            for (Document row : rows) {
                if (row == null || row.id == null || row.id.isEmpty() || row.id.length() > 4096
                        || (row.size != null && row.size < 0))
                    throw fail(Code.INVALID_METADATA, "Malformed document metadata");
                validateName(row.name); // Even unused unknown payload names must be safe.
                if (names.putIfAbsent(row.name, row) != null || !keys.add(fold(row.name)))
                    throw fail(Code.INVALID_METADATA, "Duplicate exact/caseless document name");
                if (!ids.add(row.id)) throw fail(Code.INVALID_METADATA, "Document-ID path alias");
            }
            exact = Collections.unmodifiableMap(names);
        }
    }
    private static final class Namespace {
        final Provider provider; final Operation operation;
        final Map<String, Listing> cache = new HashMap<>();
        final Map<String, String> idPaths = new HashMap<>();
        int rows;
        Namespace(Provider provider, Operation operation, Document root) throws IOException {
            this.provider = provider; this.operation = operation;
            if (root == null || root.id == null || root.id.isEmpty() || root.id.length() > 4096
                    || !root.directory || root.virtual)
                throw fail(Code.INVALID_METADATA, "Tree root is not an ordinary directory");
            validateName(root.name);
            if (root.size != null && root.size < 0)
                throw fail(Code.INVALID_METADATA, "Negative root metadata size");
            idPaths.put(root.id, "");
        }
        Listing list(Document dir, String path, int depth) throws IOException {
            operation.check();
            if (depth > MAX_DEPTH) throw fail(Code.LIMIT, "Directory depth exceeds 64");
            Listing existing = cache.get(dir.id);
            if (existing != null) return existing;
            Listing result = new Listing(provider.children(dir, operation));
            if (rows > MAX_NAMESPACE - result.exact.size())
                throw fail(Code.LIMIT, "Namespace exceeds 65536 rows");
            rows += result.exact.size();
            for (Document child : result.exact.values()) {
                String childPath = path + "/" + child.name;
                String previous = idPaths.putIfAbsent(child.id, childPath);
                if (previous != null && !previous.equals(childPath))
                    throw fail(Code.INVALID_METADATA, "Directory cycle or cross-path document-ID alias");
            }
            cache.put(dir.id, result);
            return result;
        }
    }
    private static final class Located {
        final Document document; final String path; final int depth;
        Located(Document document, String path, int depth) {
            this.document = document; this.path = path; this.depth = depth;
        }
    }
    private static boolean candidate(Listing listing) {
        Document main = listing.exact.get("main"), data = listing.exact.get("data");
        return main != null && !main.directory && !main.virtual
                && data != null && data.directory && !data.virtual;
    }
    private static Located locateRoot(Namespace namespace, Document root) throws IOException {
        Located selected = new Located(root, "", 0);
        Listing direct = namespace.list(root, "", 0);
        if (candidate(direct)) return selected;
        Deque<Located> queue = new ArrayDeque<>();
        queue.add(selected);
        Located found = null;
        int queried = 1;
        while (!queue.isEmpty()) {
            Located current = queue.removeFirst();
            Listing list = namespace.list(current.document, current.path, current.depth);
            if (current.depth != 0 && candidate(list)) {
                if (found != null) throw fail(Code.AMBIGUOUS_ROOT, "Multiple main+data roots; choose a narrower tree");
                found = current;
                continue; // Never enumerate payload descendants of an accepted root.
            }
            for (Document child : list.exact.values()) {
                if (!child.directory || child.virtual) continue;
                if (current.depth >= MAX_WRAPPER_DEPTH || ++queried > MAX_WRAPPER_DIRECTORIES)
                    throw fail(Code.LIMIT, "Wrapper search exceeds depth 8 or 256 directories; choose a narrower tree");
                queue.addLast(new Located(child, current.path + "/" + child.name, current.depth + 1));
            }
        }
        if (found == null) throw fail(Code.NO_ROOT, "No ordinary exact-case main+data root; no payload read");
        return found;
    }
    private static Document resolve(Namespace namespace, Located root, Expected expected) throws IOException {
        Document current = root.document;
        String currentPath = root.path;
        int depth = root.depth;
        String[] segments = expected.path.split("/");
        for (int i = 0; i < segments.length; i++) {
            Document child = namespace.list(current, currentPath, depth).exact.get(segments[i]);
            if (child == null) throw fail(Code.SOURCE_MISSING, "Missing exact-case audited source: " + expected.path);
            if (child.virtual) throw fail(Code.INVALID_METADATA, "Virtual audited source is not accepted");
            boolean intermediate = i < segments.length - 1;
            if (child.directory != intermediate)
                throw fail(Code.INVALID_METADATA, "Audited source file/directory substitution");
            if (!intermediate) {
                if (child.size != null && child.size != expected.length)
                    throw fail(Code.SIZE_MISMATCH, "Known source size differs from profile: " + expected.path);
                return child;
            }
            current = child; currentPath += "/" + child.name; depth++;
        }
        throw fail(Code.SOURCE_MISSING, "Empty source path");
    }

    interface Space { long available(Path root) throws IOException; }
    private static final Space SYSTEM_SPACE = root -> root.toFile().getUsableSpace();
    private static void requireSpace(Space space, Path root, long bytes) throws IOException {
        if (bytes < 0 || bytes > Long.MAX_VALUE - FREE_SPACE_RESERVE
                || space.available(root) < bytes + FREE_SPACE_RESERVE)
            throw fail(Code.SPACE, "Insufficient private-job space (64 MiB reserve required)");
    }
    static Receipt copyTree(Provider provider, JobArea area, Plan plan, Cancel cancel,
                            Progress progress, Space space) throws IOException {
        try (Operation op = new Operation(cancel)) {
            area.verify();
            report(progress, "validate-tree", 0, plan.bytes);
            Document root = provider.root(op);
            Namespace namespace = new Namespace(provider, op, root);
            Located selected = locateRoot(namespace, root);
            // Metadata only, all required files resolved before any source body is opened.
            List<Document> documents = new ArrayList<>();
            for (Expected expected : plan.files) documents.add(resolve(namespace, selected, expected));
            op.check(); area.verify(); requireSpace(space, area.root, plan.bytes);
            Path incoming = area.freshIncoming();
            List<CopiedFile> copied = new ArrayList<>();
            long done = 0;
            for (int i = 0; i < plan.files.size(); i++) {
                Expected expected = plan.files.get(i);
                CopiedFile result = copyExpected(provider, documents.get(i), expected, area, incoming,
                        op, progress, done, plan.bytes, space);
                copied.add(result); done += result.length;
            }
            // Keep the core receipt and progress tied to the sealed 0.74 profile.
            copyOptionalSources(AURA_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(MILEAGE_MENU_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(GHOST_MATCH_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(GHOST_WHEEL_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(FINISH_MENU_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(CROWN_SCENE_SOURCES, provider, namespace, selected, area, incoming, op, space);
            copyOptionalSources(TEN_BGM_SOURCES, provider, namespace, selected, area, incoming, op, space);
            op.check(); area.verify(); report(progress, "staged-provisional", done, plan.bytes);
            op.check(); area.verify();
            return new Receipt(copied, done);
        }
    }
    private static void copyOptionalSources(List<Expected> sources, Provider provider,
                                            Namespace namespace, Located selected, JobArea area,
                                            Path incoming, Operation op, Space space) throws IOException {
        try {
            List<Document> documents = new ArrayList<>();
            List<Expected> missing = new ArrayList<>();
            for (Expected expected : sources) {
                // Shared assets may already be in the signed core or another optional group.
                // The converter still authenticates each member against its read-set.
                if (Files.isRegularFile(area.target(incoming, expected.path), NOFOLLOW)) continue;
                documents.add(resolve(namespace, selected, expected));
                missing.add(expected);
            }
            for (int i = 0; i < missing.size(); i++) {
                Expected expected = missing.get(i);
                copyExpected(provider, documents.get(i), expected, area, incoming,
                        op, null, 0, expected.length, space);
            }
        } catch (IOException unavailable) {
            op.check();
            area.verify();
        }
    }

    private static CopiedFile copyExpected(Provider provider, Document document, Expected expected,
                                            JobArea area, Path incoming, Operation op, Progress progress,
                                            long done, long total, Space space) throws IOException {
        op.check(); area.verify(); requireSpace(space, area.root, expected.length);
        Path target = area.target(incoming, expected.path);
        try (FileChannel output = area.newFile(target)) {
            ReadHandle source = provider.open(document, op);
            if (source == null) throw new IOException("Provider returned no source descriptor");
            op.track(source);
            try {
                CopiedFile result = transfer(source, output, expected.path, expected.length,
                        expected.sha256, op, progress, done, total, space, area.root);
                op.check(); area.verify(); output.force(true);
                return result;
            } finally { op.release(source); }
        }
    }

    static Receipt copyZip(Provider provider, JobArea area, Cancel cancel,
                           Progress progress, Space space) throws IOException {
        try (Operation op = new Operation(cancel)) {
            area.verify();
            report(progress, "archive-limit-8GiB", 0, MAX_ZIP_BYTES);
            op.check();
            requireSpace(space, area.root, 0);
            Path target = area.root.resolve("incoming.zip");
            try (FileChannel output = area.newFile(target)) {
                Document document = provider.root(op);
                if (document == null || document.directory || document.virtual)
                    throw fail(Code.INVALID_METADATA, "ZIP URI must be an ordinary readable document");
                if (document.size != null && (document.size < 0 || document.size > MAX_ZIP_BYTES))
                    throw fail(Code.LIMIT, "Compressed archive exceeds 8 GiB");
                if (document.size != null) requireSpace(space, area.root, document.size);
                ReadHandle source = provider.open(document, op);
                if (source == null) throw new IOException("Provider returned no source descriptor");
                op.track(source);
                try {
                    CopiedFile result = transfer(source, output, "incoming.zip", MAX_ZIP_BYTES,
                            null, op, progress, 0, MAX_ZIP_BYTES, space, area.root);
                    op.check(); area.verify(); output.force(true);
                    // Provisional 0600; later snapshot sealing is deliberately separate.
                    report(progress, "staged-provisional", result.length, result.length);
                    op.check(); area.verify();
                    return new Receipt(Collections.singletonList(result), result.length);
                } finally { op.release(source); }
            }
        }
    }
    static CopiedFile transfer(ReadHandle source, FileChannel output, String name, long limit,
                               String expectedSha, Operation op, Progress progress, long completed,
                               long total, Space space, Path jobRoot) throws IOException {
        MessageDigest digest = sha256();
        byte[] buffer = new byte[BUFFER_BYTES];
        long count = 0;
        int zeros = 0;
        InputStream input = source.input();
        report(progress, expectedSha == null ? "copy-zip" : name.equals("main") ? "copy-main" : "copy-source",
                completed, total);
        while (true) {
            op.check();
            // The extra byte detects overruns without ever writing the overrun.
            int requested = (int) Math.min(buffer.length, limit - count + 1);
            int n;
            try { n = input.read(buffer, 0, requested); }
            catch (IOException e) { op.check(); throw e; }
            op.check();
            if (n == -1) break;
            if (n < -1 || n > requested) throw new IOException("Provider returned an invalid stream byte count");
            if (n == 0) {
                if (++zeros > 16) throw new IOException("Provider stream repeatedly returned zero bytes");
                continue;
            }
            zeros = 0;
            if (n > limit - count)
                throw fail(expectedSha == null ? Code.LIMIT : Code.SIZE_MISMATCH,
                        expectedSha == null ? "Compressed archive exceeds 8 GiB" : "Source exceeds profile length");
            requireSpace(space, jobRoot, n);
            ByteBuffer bytes = ByteBuffer.wrap(buffer, 0, n);
            while (bytes.hasRemaining()) { op.check(); output.write(bytes); }
            digest.update(buffer, 0, n); count += n;
            report(progress, expectedSha == null ? "copy-zip" : name.equals("main") ? "copy-main" : "copy-source",
                    completed + count, total);
        }
        if (expectedSha != null && count != limit)
            throw fail(Code.SIZE_MISMATCH, "Source shorter than profile length");
        String hash = hex(digest.digest());
        if (expectedSha != null && !hash.equals(expectedSha))
            throw fail(Code.HASH_MISMATCH, "Source SHA-256 differs from audited profile");
        return new CopiedFile(name, count, hash, source.fdKind);
    }
    private static MessageDigest sha256() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static String hex(byte[] bytes) {
        char[] text = new char[bytes.length * 2];
        char[] digits = "0123456789abcdef".toCharArray();
        for (int i = 0; i < bytes.length; i++) {
            text[i * 2] = digits[(bytes[i] >>> 4) & 15]; text[i * 2 + 1] = digits[bytes[i] & 15];
        }
        return new String(text);
    }
    private static void report(Progress progress, String stage, long current, long total) {
        if (progress != null) progress.update(stage, current, total);
    }

    static final class JobArea {
        final Path root, jobs, noBackup, owner;
        final Object rootKey, jobsKey, ownerKey;
        final UserPrincipal principal;
        final byte[] ownerBytes;
        private JobArea(Path noBackup, Path jobs, Path root, String profileSha) throws IOException {
            this.noBackup = noBackup; this.jobs = jobs; this.root = root; this.owner = root.resolve("owner.tsv");
            principal = Files.getOwner(noBackup, NOFOLLOW);
            checkDirectory(jobs, principal); checkDirectory(root, principal);
            rootKey = key(root); jobsKey = key(jobs);
            BasicFileAttributes attrs = Files.readAttributes(owner, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isRegularFile() || attrs.size() > 1024 || !Files.getOwner(owner, NOFOLLOW).equals(principal)
                    || !Files.getPosixFilePermissions(owner, NOFOLLOW).equals(FILE_MODE))
                throw fail(Code.INVALID_JOB, "Missing regular private owner record");
            ownerKey = attrs.fileKey();
            if (rootKey == null || jobsKey == null || ownerKey == null)
                throw fail(Code.INVALID_JOB, "Stable job identity unavailable");
            ownerBytes = readOwner(owner);
            String text = new String(ownerBytes, StandardCharsets.US_ASCII);
            String prefix = "WMMT-ORIGINAL-JOB-1\njob\t" + root.getFileName() + "\nnonce\t";
            String suffix = "\nprofile\t" + profileSha + "\nEND\n";
            if (!text.startsWith(prefix) || !text.endsWith(suffix)
                    || !hex64(text.substring(prefix.length(), text.length() - suffix.length())))
                throw fail(Code.INVALID_JOB, "Owner record is not bound to this job/profile");
            verify();
        }
        static JobArea open(Path trustedNoBackup, Path jobRoot, String profileSha) throws IOException {
            if (trustedNoBackup == null || jobRoot == null || !hex64(profileSha)
                    || !jobRoot.isAbsolute() || !jobRoot.equals(jobRoot.normalize()))
                throw fail(Code.INVALID_JOB, "Job path must be exact absolute canonical path");
            Path noBackup = trustedNoBackup.toRealPath();
            Path jobs = noBackup.resolve("re3dxplus-original-jobs");
            String id = jobRoot.getFileName() == null ? "" : jobRoot.getFileName().toString();
            try {
                if (!UUID.fromString(id).toString().equals(id))
                    throw fail(Code.INVALID_JOB, "Job ID is not a canonical UUID");
            } catch (IllegalArgumentException e) { throw fail(Code.INVALID_JOB, "Job ID is not a canonical UUID"); }
            if (!jobRoot.equals(jobs.resolve(id)) || !jobRoot.equals(jobRoot.toRealPath()))
                throw fail(Code.INVALID_JOB, "Job is outside canonical noBackup job namespace");
            return new JobArea(noBackup, jobs, jobRoot, profileSha);
        }
        void verify() throws IOException {
            if (!root.equals(root.toRealPath()) || !jobs.equals(jobs.toRealPath())
                    || !Files.getOwner(noBackup, NOFOLLOW).equals(principal)
                    || !rootKey.equals(key(root)) || !jobsKey.equals(key(jobs)))
                throw fail(Code.INVALID_JOB, "Job directory identity changed");
            checkDirectory(jobs, principal); checkDirectory(root, principal);
            BasicFileAttributes attrs = Files.readAttributes(owner, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isRegularFile() || !ownerKey.equals(attrs.fileKey()) || attrs.size() != ownerBytes.length
                    || !Files.getOwner(owner, NOFOLLOW).equals(principal)
                    || !Files.getPosixFilePermissions(owner, NOFOLLOW).equals(FILE_MODE)
                    || !Arrays.equals(ownerBytes, readOwner(owner)))
                throw fail(Code.INVALID_JOB, "Job owner record changed");
        }
        Path freshIncoming() throws IOException {
            verify();
            Path incoming = root.resolve("incoming");
            Files.createDirectory(incoming, PosixFilePermissions.asFileAttribute(DIR_MODE));
            checkDirectory(incoming, principal);
            return incoming;
        }
        Path target(Path incoming, String relative) throws IOException {
            verify(); validateRelative(relative);
            if (!incoming.equals(root.resolve("incoming"))) throw fail(Code.INVALID_JOB, "Wrong staging root");
            checkDirectory(incoming, principal);
            Path current = incoming;
            String[] segments = relative.split("/");
            for (int i = 0; i < segments.length - 1; i++) {
                current = current.resolve(segments[i]);
                if (!Files.exists(current, NOFOLLOW))
                    Files.createDirectory(current, PosixFilePermissions.asFileAttribute(DIR_MODE));
                checkDirectory(current, principal);
            }
            return current.resolve(segments[segments.length - 1]);
        }
        FileChannel newFile(Path target) throws IOException {
            verify();
            Path normalized = target.toAbsolutePath().normalize();
            if (!normalized.equals(target) || !target.startsWith(root) || target.equals(root))
                throw fail(Code.INVALID_JOB, "Target escaped job");
            Path parent = target.getParent();
            while (!parent.equals(root)) {
                checkDirectory(parent, principal);
                parent = parent.getParent();
            }
            return FileChannel.open(target,
                    new HashSet<>(Arrays.asList(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE,
                            LinkOption.NOFOLLOW_LINKS)), PosixFilePermissions.asFileAttribute(FILE_MODE));
        }
        private static byte[] readOwner(Path path) throws IOException {
            try (FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer buffer = ByteBuffer.allocate(1025);
                while (buffer.hasRemaining() && channel.read(buffer) != -1) { }
                if (buffer.position() > 1024) throw fail(Code.INVALID_JOB, "Owner record too large");
                return Arrays.copyOf(buffer.array(), buffer.position());
            }
        }
        private static Object key(Path path) throws IOException {
            return Files.readAttributes(path, BasicFileAttributes.class, NOFOLLOW).fileKey();
        }
        private static void checkDirectory(Path path, UserPrincipal owner) throws IOException {
            BasicFileAttributes attrs = Files.readAttributes(path, BasicFileAttributes.class, NOFOLLOW);
            if (!attrs.isDirectory() || !Files.getOwner(path, NOFOLLOW).equals(owner)
                    || !Files.getPosixFilePermissions(path, NOFOLLOW).equals(DIR_MODE))
                throw fail(Code.INVALID_JOB, "Job directory must be private, owned, and no-follow");
        }
    }

    private static final class SafProvider implements Provider {
        private static final String[] COLUMNS = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_FLAGS,
            DocumentsContract.Document.COLUMN_SIZE
        };
        final ContentResolver resolver; final Uri selected; final boolean tree;
        SafProvider(ContentResolver resolver, Uri selected, boolean tree) {
            this.resolver = resolver; this.selected = selected; this.tree = tree;
        }
        private Cursor query(Uri uri, Operation operation) throws IOException {
            operation.check();
            CancellationSignal signal = new CancellationSignal();
            Closeable signalOwner = signal::cancel;
            operation.track(signalOwner);
            try {
                Cursor cursor = resolver.query(uri, COLUMNS, null, null, null, signal);
                if (cursor == null) throw new IOException("Provider returned no metadata cursor");
                operation.track(cursor);
                operation.check();
                return cursor;
            } finally { operation.forget(signalOwner); }
        }
        @Override public Document root(Operation operation) throws IOException {
            if (!tree) return new Document("opaque-zip", "incoming.zip", false, false, null);
            String id = DocumentsContract.getTreeDocumentId(selected);
            Uri uri = DocumentsContract.buildDocumentUriUsingTree(selected, id);
            Cursor cursor = query(uri, operation);
            try {
                if (!cursor.moveToNext()) throw fail(Code.INVALID_METADATA, "Missing tree-root document");
                Document root = row(cursor);
                if (!id.equals(root.id) || cursor.moveToNext())
                    throw fail(Code.INVALID_METADATA, "Ambiguous tree-root metadata");
                return root;
            } finally { operation.release(cursor); }
        }
        @Override public List<Document> children(Document directory, Operation operation) throws IOException {
            Uri uri = DocumentsContract.buildChildDocumentsUriUsingTree(selected, directory.id);
            Cursor cursor = query(uri, operation);
            try {
                List<Document> result = new ArrayList<>();
                while (cursor.moveToNext()) {
                    operation.check();
                    if (result.size() >= MAX_CHILDREN) throw fail(Code.LIMIT, "Directory exceeds 16384 rows");
                    result.add(row(cursor));
                }
                return result;
            } finally { operation.release(cursor); }
        }
        private static Document row(Cursor cursor) throws IOException {
            int id = cursor.getColumnIndexOrThrow(COLUMNS[0]);
            int name = cursor.getColumnIndexOrThrow(COLUMNS[1]);
            int mime = cursor.getColumnIndexOrThrow(COLUMNS[2]);
            int flags = cursor.getColumnIndexOrThrow(COLUMNS[3]);
            int size = cursor.getColumnIndexOrThrow(COLUMNS[4]);
            if (cursor.getType(id) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(name) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(mime) != Cursor.FIELD_TYPE_STRING
                    || cursor.getType(flags) != Cursor.FIELD_TYPE_INTEGER)
                throw fail(Code.INVALID_METADATA, "Incomplete SAF row");
            Long length = null;
            if (!cursor.isNull(size)) {
                if (cursor.getType(size) != Cursor.FIELD_TYPE_INTEGER)
                    throw fail(Code.INVALID_METADATA, "Nonnumeric SAF size");
                long value = cursor.getLong(size);
                if (value >= 0) length = value; // Negative/unknown provider sizes stay unknown.
            }
            String type = cursor.getString(mime);
            if (type == null || type.isEmpty()) throw fail(Code.INVALID_METADATA, "Missing MIME type");
            long flagValue = cursor.getLong(flags);
            if (flagValue < 0 || flagValue > Integer.MAX_VALUE)
                throw fail(Code.INVALID_METADATA, "Invalid SAF flags");
            int bits = (int) flagValue;
            return new Document(cursor.getString(id), cursor.getString(name),
                    DocumentsContract.Document.MIME_TYPE_DIR.equals(type),
                    (bits & DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT) != 0, length);
        }
        @Override public ReadHandle open(Document document, Operation operation) throws IOException {
            operation.check();
            Uri uri = tree ? DocumentsContract.buildDocumentUriUsingTree(selected, document.id) : selected;
            CancellationSignal signal = new CancellationSignal();
            Closeable signalOwner = signal::cancel;
            operation.track(signalOwner);
            AssetFileDescriptor afd = null;
            ReadHandle handle = null;
            try {
                afd = resolver.openAssetFileDescriptor(uri, "r", signal);
                if (afd == null) throw new IOException("Provider returned no read-only descriptor");
                String kind = "unknown";
                try {
                    ParcelFileDescriptor pfd = afd.getParcelFileDescriptor();
                    StructStat stat = Os.fstat(pfd.getFileDescriptor());
                    kind = OsConstants.S_ISREG(stat.st_mode) ? "regular-observed" : "nonregular-stream";
                } catch (ErrnoException | RuntimeException ignored) { /* Do not pretend pipe==regular. */ }
                handle = new ReadHandle((Closeable) afd, kind);
                operation.track(handle);
                operation.check();
                if (!tree && afd.getLength() > MAX_ZIP_BYTES)
                    throw fail(Code.LIMIT, "Compressed archive descriptor length exceeds 8 GiB");
                if (tree && document.size != null && afd.getLength() >= 0
                        && afd.getLength() != document.size)
                    throw fail(Code.SIZE_MISMATCH, "Descriptor length differs from document metadata");
                handle.attach(afd.createInputStream());
                operation.check();
                return handle;
            } catch (IOException | RuntimeException e) {
                if (handle != null) operation.release(handle);
                else if (afd != null) afd.close();
                operation.check();
                throw e;
            } finally { operation.forget(signalOwner); }
        }
    }
}
