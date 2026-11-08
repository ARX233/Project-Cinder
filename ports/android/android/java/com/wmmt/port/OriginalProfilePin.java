package com.wmmt.port;
final class OriginalProfilePin {
 static final String ASSET="original-convert/profile.tsv";
 static final String SHA256="dd5ba7761175b83652ff304f40fdc20fbb93d26d2aa5cb883e914ae9ff825f20";
 static final String UPGRADE_HINT="原版转换配置已更新，请重新转换。旧资源和存档会保留。";
 static boolean requiresReconversion(String previous) {
  // Only authenticated, explicitly known older original profiles receive the
  // upgrade explanation. Unknown profiles still fail closed as before.
  return "fffcd9c9709fed82eedb55c1fa7e1784d1cd6ec12daeb9a3515f151efda87baf".equals(previous)
       || "d33ba32c55d030a367aeb9561d95523ca8841904549a39719c4f05dbdbe586a5".equals(previous)
       || "c2bee14d98de3c7840d7c6ae8badf9e150bdd96f3e624a468119546e5ebe66a9".equals(previous)
      || "b9b7e92ccee4c398c0bca8472316a5dc04265bdb5b42ff1d6dc3ee215f363850".equals(previous);
 }
 private OriginalProfilePin() {}
}
