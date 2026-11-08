package com.wmmt.port;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.security.*;
import java.text.Normalizer;
import java.util.*;

/** APK-pinned conversion contract, never an inventory supplied by a player.
 * expectedSha256 MUST come from a reviewed constant in the signed APK. Hashes of
 * generated outputs may be absent: they are authenticated by controlled job
 * execution, not by pretending a later HMAC is a pre-signed reference output. */
public final class OriginalProfile {
    public static final int OUTPUT_COUNT = 1801;
    public static final long MAIN_LENGTH = 24855892L;
    public static final String MAIN_SHA256 = "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6";
    private static final long GIB = 1024L * 1024 * 1024;
    private static final int MAX_BYTES = 8 * 1024 * 1024;

    public static final class Source {
        public final String path, sha256;
        public final long length;
        private Source(String p, long n, String h) { path=p; length=n; sha256=h; }
    }
    public static final class Output {
        public final String path, exactSha256, kind;
        public final long maxLength;
        private Output(String p, long n, String h, String k) { path=p; maxLength=n; exactSha256=h; kind=k; }
    }
    public final String profileId, readsetSha256, recipeSha256, sha256;
    public final long sourceBytes, maxOutputBytes;
    public final SortedMap<String,Source> sources;
    public final SortedMap<String,Output> outputs;
    private OriginalProfile(String id, String readset, String recipe, String digest,
            long sourceTotal, long outputTotal, SortedMap<String,Source> src, SortedMap<String,Output> out) {
        profileId=id; readsetSha256=readset; recipeSha256=recipe; sha256=digest;
        sourceBytes=sourceTotal; maxOutputBytes=outputTotal;
        sources=Collections.unmodifiableSortedMap(new TreeMap<String,Source>(src));
        outputs=Collections.unmodifiableSortedMap(new TreeMap<String,Output>(out));
    }
    public SortedMap<String,Source> sources() { return sources; }
    public SortedMap<String,Output> outputs() { return outputs; }

    public static OriginalProfile read(InputStream input, String expectedSha256) throws IOException {
        hashSyntax(expectedSha256);
        if(input==null) throw bad("Missing APK profile");
        byte[] bytes=bounded(input,MAX_BYTES);
        String digest=hex(sha().digest(bytes));
        if(!MessageDigest.isEqual(digest.getBytes(StandardCharsets.US_ASCII),expectedSha256.getBytes(StandardCharsets.US_ASCII)))
            throw bad("APK profile SHA-256 mismatch");
        String[] lines=lines(bytes);
        if(lines.length<7 || !lines[0].equals("WMMT-ORIGINAL-PROFILE-1")) throw bad("Profile version");
        String id=header(lines[1],"profileId"),readset=header(lines[2],"readsetSha256"),recipe=header(lines[3],"recipeSha256");
        asciiId(id); hashSyntax(readset); hashSyntax(recipe);
        SortedMap<String,Source> src=new TreeMap<String,Source>();
        SortedMap<String,Output> out=new TreeMap<String,Output>();
        PathRoster srcPaths=new PathRoster(),outPaths=new PathRoster();
        String previousSource=null,previousOutput=null;
        long sourceTotal=0,outputTotal=0; boolean outputPhase=false;
        for(int i=4;i<lines.length-1;i++) {
            String[] f=lines[i].split("\t",-1);
            if(f.length==4 && f[0].equals("src") && !outputPhase) {
                path(f[1],false); srcPaths.add(f[1]);
                if(previousSource!=null && previousSource.compareTo(f[1])>=0) throw bad("Unsorted or duplicate source");
                long n=number(f[2],2*GIB); hashSyntax(f[3]);
                if(src.size()>=16384 || n>32*GIB-sourceTotal) throw bad("Source limits");
                sourceTotal+=n; src.put(f[1],new Source(f[1],n,f[3])); previousSource=f[1];
            } else if(f.length==5 && f[0].equals("out")) {
                outputPhase=true; path(f[1],true); outPaths.add(f[1]);
                if(previousOutput!=null && previousOutput.compareTo(f[1])>=0) throw bad("Unsorted or duplicate output");
                long n=number(f[2],GIB/2); String h=f[3].equals("-")?null:f[3];
                if(h!=null) hashSyntax(h); asciiId(f[4]);
                if(out.size()>=OUTPUT_COUNT || n>32*GIB-outputTotal) throw bad("Output limits");
                outputTotal+=n; out.put(f[1],new Output(f[1],n,h,f[4])); previousOutput=f[1];
            } else throw bad("Unknown, duplicate, or misplaced profile row");
        }
        if(!lines[lines.length-1].equals("END") || out.size()!=OUTPUT_COUNT) throw bad("Incomplete profile roster");
        Source main=src.get("main");
        if(main==null || main.length!=MAIN_LENGTH || !main.sha256.equals(MAIN_SHA256)) throw bad("Original 1.35 main identity");
        return new OriginalProfile(id,readset,recipe,digest,sourceTotal,outputTotal,src,out);
    }
    static IOException bad(String s) { return new IOException(s); }
    static MessageDigest sha() { try { return MessageDigest.getInstance("SHA-256"); } catch(NoSuchAlgorithmException e) { throw new AssertionError(e); } }
    static String hex(byte[] bytes) {
        char[] digits="0123456789abcdef".toCharArray(),out=new char[bytes.length*2];
        for(int i=0;i<bytes.length;i++) { out[i*2]=digits[(bytes[i]&255)>>>4]; out[i*2+1]=digits[bytes[i]&15]; }
        return new String(out);
    }
    static void hashSyntax(String s) throws IOException { if(s==null || !s.matches("[0-9a-f]{64}")) throw bad("Invalid SHA-256"); }
    static void asciiId(String s) throws IOException { if(s==null || !s.matches("[A-Za-z0-9][A-Za-z0-9._-]{0,127}")) throw bad("Invalid ASCII identifier"); }
    static long number(String s,long max) throws IOException {
        if(!s.matches("0|[1-9][0-9]{0,18}")) throw bad("Noncanonical length");
        try { long n=Long.parseLong(s); if(n>max) throw bad("Length limit"); return n; }
        catch(NumberFormatException e) { throw new IOException("Length overflow",e); }
    }
    static byte[] bounded(InputStream in,int max) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] b=new byte[8192]; int n;
        while((n=in.read(b))!=-1) {
            if(n==0) { int one=in.read(); if(one<0) break; b[0]=(byte)one; n=1; }
            if(n>max-out.size()) throw bad("Record byte limit"); out.write(b,0,n);
        }
        return out.toByteArray();
    }
    static String[] lines(byte[] bytes) throws IOException {
        final String s;
        try { s=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch(CharacterCodingException e) { throw new IOException("Invalid UTF-8",e); }
        if(!s.endsWith("\n") || s.indexOf('\r')>=0) throw bad("Canonical LF required");
        String[] all=s.split("\n",-1); return Arrays.copyOf(all,all.length-1);
    }
    static String header(String line,String name) throws IOException {
        String[] f=line.split("\t",-1); if(f.length!=2 || !f[0].equals(name)) throw bad("Missing or misplaced "+name); return f[1];
    }
    /** NFC paths with no platform/control/reserved aliases. Source main/data are
     * permitted; no output may occupy either original input namespace. */
    static void path(String path,boolean output) throws IOException {
        if(path==null || path.isEmpty() || path.getBytes(StandardCharsets.UTF_8).length>4096 ||
                !Normalizer.isNormalized(path,Normalizer.Form.NFC) || path.startsWith("/") || path.indexOf('\\')>=0 || path.indexOf(':')>=0)
            throw bad("Unsafe or non-NFC path");
        for(int i=0;i<path.length();) {
            int c=path.codePointAt(i); int type=Character.getType(c);
            if(Character.isISOControl(c) || type==Character.FORMAT || type==Character.SURROGATE) throw bad("Control path character");
            i+=Character.charCount(c);
        }
        for(String part:path.split("/",-1)) {
            String lower=fold(part);
            if(part.isEmpty() || part.equals(".") || part.equals("..") || part.endsWith(".") || part.endsWith(" ") ||
                    lower.equals("wmmt") || lower.equals("mods") || lower.equals(".wmmt-data-manifest") ||
                    lower.equals(".re3dxplus-install-v1") || lower.startsWith(".overlay-") || lower.equals("owner.tsv") ||
                    lower.equals("job.json") || lower.equals("completion.tsv") || lower.equals("hmac.key") ||
                    lower.matches("con|prn|aux|nul|com[1-9]|lpt[1-9]") || lower.matches("(con|prn|aux|nul|com[1-9]|lpt[1-9])\\..*"))
                throw bad("Reserved path component");
        }
        String first=fold(path.split("/",2)[0]);
        if(!output && !path.equals("main") && !path.startsWith("data/")) throw bad("Source outside pinned main/data namespace");
        if(output && (first.equals("main") || first.equals("data"))) throw bad("Output aliases original source");
    }
    /** Conservative bounded case-alias key, not the complete Unicode CaseFolding
     * standard. Iterate to close multi-step mappings such as ẞ -> ß -> ss; never
     * accept a key whose NFC/ROOT upper-lower mapping did not stabilize. */
    static String fold(String s) throws IOException {
        String key=Normalizer.normalize(s,Normalizer.Form.NFC);
        for(int round=0;round<4;round++) {
            String next=Normalizer.normalize(key.toUpperCase(Locale.ROOT).toLowerCase(Locale.ROOT),Normalizer.Form.NFC);
            if(next.equals(key)) return key;
            key=next;
        }
        throw bad("Case-alias normalization did not stabilize");
    }
    static final class PathRoster {
        private final Map<String,String> spellings=new HashMap<String,String>();
        private final Set<String> files=new HashSet<String>(),directories=new HashSet<String>();
        void add(String path) throws IOException {
            String[] parts=path.split("/"); String prefix="";
            for(int i=0;i<parts.length;i++) {
                prefix=prefix.isEmpty()?parts[i]:prefix+"/"+parts[i]; String key=fold(prefix);
                String prior=spellings.putIfAbsent(key,prefix);
                if(prior!=null && !prior.equals(prefix)) throw bad("Case-fold path/directory alias");
                boolean last=i==parts.length-1;
                if(last) { if(!files.add(key) || directories.contains(key)) throw bad("Duplicate or ancestor file alias"); }
                else { if(files.contains(key)) throw bad("Ancestor file alias"); directories.add(key); }
            }
        }
    }
}
