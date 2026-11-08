package com.wmmt.port;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.util.*;

/** Sidecar inventories authenticated by the APK signature, never by an imported manifest.
 * The caller owns the input stream. Missing metadata disables the corresponding feature. */
public final class ResourceMetadata {
    public static final int MAX_BYTES = 64 * 1024, MAX_ENTRIES = 512;
    public static final List<String> OPTIONAL_PATHS = Collections.unmodifiableList(Arrays.asList(
            "story-cutin.bin", "card-pages.bin", "backfire.wpk", "backfire.bfx", "ghost-ui.bin", "builtin-ghosts.bin"));
    public static final String BUILTIN_GHOSTS_PATH="builtin-ghosts.bin";
    public static final long BUILTIN_GHOSTS_LIMIT=256L*1024*1024;
    public static final String GHOST_UI_PATH="ghost-ui.bin";
    public static final long GHOST_UI_LIMIT=256L*1024*1024;
    static final List<String> FRONT_HALO_PATHS=Collections.unmodifiableList(Arrays.asList("front_halo.wpk", "front_halo.bin"));
    public static final List<String> CARD_PATHS;
    private static final Set<String> ALLOWED;
    static {
        List<String> cards = new ArrayList<String>();
        cards.add("card-resources/manifest.json"); cards.add("card-resources/meters-v2.bin");
        for (int i=1;i<=23;i++) cards.add(String.format(Locale.ROOT,"card-resources/bgm-extra/wm2_%02d.m4a",i));
        for (int i=1;i<=12;i++) cards.add(String.format(Locale.ROOT,"card-resources/bgm-extra/wmr_%02d.m4a",i));
        CARD_PATHS=Collections.unmodifiableList(cards);
        Set<String> paths=new HashSet<String>(OPTIONAL_PATHS.subList(0,4)); paths.addAll(cards); ALLOWED=Collections.unmodifiableSet(paths);
    }
    public static final class Entry {
        public final String path, sha256; public final long length;
        private Entry(String p,long l,String h) { path=p; length=l; sha256=h; }
    }
    private final SortedMap<String,Entry> entries;
    private ResourceMetadata(SortedMap<String,Entry> e) { entries=Collections.unmodifiableSortedMap(e); }
    public SortedMap<String,Entry> files() { return entries; }
    public Entry find(String path) { return entries.get(path); }
    static boolean allowed(String path) { return ALLOWED.contains(path); }
    /** Fixed output of pack_front_halo.py on the reviewed DX+ arcade data. Like
     * the APK's metadata, these approvals cannot be supplied by a ZIP. */
    ResourceMetadata withFrontHalo() {
        SortedMap<String,Entry> merged=new TreeMap<String,Entry>(entries);
        merged.put("front_halo.wpk",new Entry("front_halo.wpk",524384,
                "36d05929a826676d93ddae2428085ec6e831723b8edceba72dc38131c3a2644a"));
        merged.put("front_halo.bin",new Entry("front_halo.bin",26304,
                "ee1ee36cd3f23834ebdf048447399d2594f79af24f97dbc90a7f0356a2185bfc"));
        return new ResourceMetadata(merged);
    }
    public static ResourceMetadata read(InputStream input) throws IOException {
        if(input==null) throw new IOException("缺少附加资源校验目录");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); byte[] b=new byte[4096]; int n;
        while((n=input.read(b))!=-1) {
            if(n==0) { int one=input.read(); if(one<0) break; if(bytes.size()==MAX_BYTES) throw bad(); bytes.write(one); continue; }
            if(n>MAX_BYTES-bytes.size()) throw bad(); bytes.write(b,0,n);
        }
        String text;
        try { text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString(); }
        catch(CharacterCodingException e) { throw bad(); }
        if(!text.startsWith("WMMT-SIDECARS-1\n") || !text.endsWith("\n")) throw bad();
        String[] lines=text.split("\n",-1); SortedMap<String,Entry> result=new TreeMap<String,Entry>(); String previous=null;
        for(int i=1;i<lines.length-1;i++) {
            String[] f=lines[i].split("\t",-1);
            if(f.length!=3 || !allowed(f[0]) || (previous!=null && previous.compareTo(f[0])>=0) ||
                    !f[1].matches("0|[1-9][0-9]{0,18}") || !f[2].matches("[0-9a-f]{64}") || result.size()>=MAX_ENTRIES) throw bad();
            long length; try { length=Long.parseLong(f[1]); } catch(NumberFormatException e) { throw bad(); }
            result.put(f[0],new Entry(f[0],length,f[2])); previous=f[0];
        }
        return new ResourceMetadata(result);
    }
    /** Separate signed APK namespace: the old 41-row index remains unchanged.
     * This method never accepts an imported manifest as an approval source. */
    public ResourceMetadata withGhost(InputStream input) throws IOException {
        return withUiApproval(input,"WMMT-GHOST-UI-1");
    }
    /** Explicit v5 opt-in in the SAME optional key. Legacy metadata is not widened. */
    public ResourceMetadata withArcadeUiV5(InputStream input) throws IOException {
        return withUiApproval(input,"WMMT-ARCADE-UI-5");
    }
    /** Repaint UI v6 explicitly replaces, never merges with, an older UI approval. */
    public ResourceMetadata withArcadeUiV6(InputStream input) throws IOException {
        return withUiApproval(input,"WMMT-ARCADE-UI-6");
    }
    private ResourceMetadata withUiApproval(InputStream input, String magic) throws IOException {
        if(input==null) throw bad();
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); byte[] b=new byte[256]; int n;
        while((n=input.read(b))!=-1) {
            if(n==0) { int one=input.read(); if(one<0) break; if(bytes.size()==512) throw bad(); bytes.write(one); continue; }
            if(n>512-bytes.size()) throw bad(); bytes.write(b,0,n);
        }
        String text;
        try { text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString(); }
        catch(CharacterCodingException e) { throw bad(); }
        String[] lines=text.split("\n",-1);
        if(lines.length!=3 || !lines[0].equals(magic) || !lines[2].isEmpty()) throw bad();
        String[] f=lines[1].split("\t",-1);
        if(f.length!=3 || !f[0].equals(GHOST_UI_PATH) || !f[1].matches("[1-9][0-9]{0,8}") || !f[2].matches("[0-9a-f]{64}")) throw bad();
        long size; try { size=Long.parseLong(f[1]); } catch(NumberFormatException e) { throw bad(); }
        if(size<16 || size>GHOST_UI_LIMIT || entries.containsKey(GHOST_UI_PATH)) throw bad();
        SortedMap<String,Entry> merged=new TreeMap<String,Entry>(entries);
        merged.put(GHOST_UI_PATH,new Entry(GHOST_UI_PATH,size,f[2]));
        return new ResourceMetadata(merged);
    }
    /** Independent sixth namespace. Never expands the old 41-row whitelist. */
    public ResourceMetadata withBuiltinGhosts(InputStream input) throws IOException {
        if(input==null) throw bad();
        ByteArrayOutputStream bytes=new ByteArrayOutputStream(); byte[] b=new byte[256]; int n;
        while((n=input.read(b))!=-1) {
            if(n==0) { int one=input.read(); if(one<0) break; if(bytes.size()==512) throw bad(); bytes.write(one); continue; }
            if(n>512-bytes.size()) throw bad(); bytes.write(b,0,n);
        }
        String text;
        try { text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString(); }
        catch(CharacterCodingException e) { throw bad(); }
        String[] lines=text.split("\n",-1);
        if(lines.length!=3 || !lines[0].equals("WMMT-BUILTIN-GHOSTS-1") || !lines[2].isEmpty()) throw bad();
        String[] f=lines[1].split("\t",-1);
        if(f.length!=3 || !f[0].equals(BUILTIN_GHOSTS_PATH) || !f[1].matches("[1-9][0-9]{0,8}") || !f[2].matches("[0-9a-f]{64}")) throw bad();
        long size; try { size=Long.parseLong(f[1]); } catch(NumberFormatException e) { throw bad(); }
        if(size<128 || size>BUILTIN_GHOSTS_LIMIT || entries.containsKey(BUILTIN_GHOSTS_PATH)) throw bad();
        SortedMap<String,Entry> merged=new TreeMap<String,Entry>(entries);
        merged.put(BUILTIN_GHOSTS_PATH,new Entry(BUILTIN_GHOSTS_PATH,size,f[2]));
        return new ResourceMetadata(merged);
    }
    private static IOException bad() { return new IOException("附加资源校验目录无效"); }
}
