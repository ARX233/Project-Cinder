/* Explicit buffer/program resources, included after native_vk.inc and the native
 * image resources. Only allocation, object tables, immutable reflection and
 * serial retirement are shared; no compatibility binding state is consulted. */

/* bufmem_try_new provides coherent, host-visible memory with vertex/index/transfer
 * usage. Its bounded map is also the CPU index-inspection source: there is no
 * separate mutable binding/shadow to synchronize. Zero bytes is not an object;
 * NULL initial data requests deterministic zero-initialized storage. */
uint32_t cinder_vk_buffer_create(size_t bytes, const void *data) {
  if (!D.dev || !bytes || bytes > PTRDIFF_MAX || (VkDeviceSize)bytes != bytes) return native_reject();
  vbufmem *m = bufmem_try_new((VkDeviceSize)bytes, BUF_USAGE);
  if (!m || !m->buf || !m->map || m->size != (VkDeviceSize)bytes) {
    if (m) bufmem_free(m);
    return native_reject();
  }
  if (data) memcpy(m->map, data, bytes);
  else memset(m->map, 0, bytes);
  uint32_t id = buf_gen();
  if (!id) { bufmem_free(m); return native_reject(); }
  buf_get(id)->m = m;
  return id;
}

int cinder_vk_buffer_update(uint32_t id, size_t offset, size_t bytes, const void *data) {
  vbuf *b = buf_get(id);
  if (!D.dev || !b || !b->m || !b->m->buf || !b->m->map || b->m->size > PTRDIFF_MAX ||
      offset > b->m->size || bytes > b->m->size - offset || (bytes && !data)) return native_reject();
  /* Validate even an empty update's handle and offset, but never allocate,
   * retire or copy for an empty span (including NULL data at the exact end). */
  if (!bytes) return 1;
  vbufmem *old = b->m, *m = old;
  if (bufmem_busy(old)) {
    m = bufmem_try_new(old->size, BUF_USAGE);
    if (!m || !m->buf || !m->map || m->size != old->size) {
      if (m) bufmem_free(m);
      return native_reject();
    }
    memcpy(m->map, old->map, (size_t)old->size);
  }
  /* memmove permits callers to use an overlapping range of this map. With
   * COW, old remains alive through this copy and any already recorded draws. */
  memmove(m->map + offset, data, bytes);
  if (m != old) {
    b->m = m;
    bufmem_drop(old);
  }
  return 1;
}

void cinder_vk_buffer_destroy(uint32_t id) {
  vbuf *b = buf_get(id);
  if (!b) return;
  vbufmem *m = b->m;
  b->m = NULL;
  buf_release(id);
  bufmem_drop(m);
}

/* The legacy parser uses atoi and allocates a temporary uniform shadow. Guard
 * its immutable input before calling it: reject signs, overflow, truncation,
 * unsupported types, invalid byte ranges and non-contiguous sampler bindings.
 * Only the generator's space/newline token grammar is admitted. */
static const char *native_object_token(const char **cursor, size_t *bytes) {
  const char *p = *cursor;
  while (*p == ' ' || *p == '\n') ++p;
  const char *start = p;
  while (*p && *p != ' ' && *p != '\n') ++p;
  *cursor = p;
  *bytes = (size_t)(p - start);
  return start;
}
static int native_object_uint(const char *p, size_t bytes, unsigned limit, unsigned *out) {
  if (!bytes) return 0;
  unsigned n = 0;
  for (size_t i = 0; i < bytes; ++i) {
    if (p[i] < '0' || p[i] > '9') return 0;
    unsigned d = (unsigned)(p[i] - '0');
    if (d > limit || n > (limit - d) / 10) return 0;
    n = n * 10 + d;
  }
  *out = n;
  return 1;
}
static int native_object_reflection(const char *refl, const char key[17]) {
  if (!refl) return 0;
  const char *cursor = refl, *p;
  size_t bytes;
  p = native_object_token(&cursor, &bytes);
  if (bytes != 16 || memcmp(p, key, 16)) return 0;
  unsigned block, inputs, n_uni = 0, samplers = 0;
  p = native_object_token(&cursor, &bytes);
  if (!native_object_uint(p, bytes, CINDER_VK_UNIFORM_BYTES, &block) || block % 16) return 0;
  p = native_object_token(&cursor, &bytes);
  if (!native_object_uint(p, bytes, (1u << CINDER_VK_ATTRIBUTES) - 1, &inputs)) return 0;
  (void)inputs;
  while (*(p = native_object_token(&cursor, &bytes))) {
    if (++n_uni > CINDER_VK_UNIFORM_BYTES / 4 + CINDER_VK_SAMPLERS) return 0;
    const char *colon = memchr(p, ':', bytes);
    size_t name = colon ? (size_t)(colon - p) : 0;
    if (!name || name >= sizeof ((vuni *)0)->name) return 0;
    for (size_t i = 0; i < name; ++i) {
      char c = p[i];
      if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || (i && c >= '0' && c <= '9'))) return 0;
    }
    const char *value = memchr(colon + 1, ':', bytes - name - 1);
    unsigned code, offset;
    if (!value || !native_object_uint(colon + 1, (size_t)(value - colon - 1), 8, &code) || !code ||
        !native_object_uint(value + 1, bytes - (size_t)(value + 1 - p), CINDER_VK_UNIFORM_BYTES, &offset)) return 0;
    if (code >= 7) {
      if (++samplers > CINDER_VK_SAMPLERS || offset != samplers) return 0;
    } else {
      static const unsigned sizes[] = {0, 4, 8, 12, 16, 4, 64};
      unsigned align = code == 2 ? 8 : code == 3 || code == 4 || code == 6 ? 16 : 4;
      if (offset % align || offset > block || sizes[code] > block - offset) return 0;
    }
  }
  return 1;
}

static int native_object_uniforms(const vprog *p) {
  /* Names must remain one-to-one for explicit packet setters. Uniform byte
   * overlaps are invalid, but std140 vec3 followed by a scalar is legal. */
  static const unsigned sizes[] = {0, 4, 8, 12, 16, 4, 64};
  for (int i = 0; i < p->n_uni; ++i) for (int j = 0; j < i; ++j) {
    const vuni *a = &p->uni[i], *b = &p->uni[j];
    if (!strcmp(a->name, b->name)) return 0;
    if (a->code < 7 && b->code < 7 &&
        (unsigned)a->off < (unsigned)b->off + sizes[b->code] &&
        (unsigned)b->off < (unsigned)a->off + sizes[a->code]) return 0;
  }
  return 1;
}
static int native_object_spirv(const uint32_t *words, int count) {
  return words && count >= 5 && (size_t)count <= SIZE_MAX / sizeof *words && words[0] == 0x07230203u;
}
static void native_object_program_free(vprog *p) {
  if (p->vs) vkDestroyShaderModule(D.dev, p->vs, NULL);
  if (p->fs) vkDestroyShaderModule(D.dev, p->fs, NULL);
  if (p->vs2) vkDestroyShaderModule(D.dev, p->vs2, NULL);
  if (p->fs2) vkDestroyShaderModule(D.dev, p->fs2, NULL);
  free(p->uni);
  free(p->shadow);
  memset(p, 0, sizeof *p);
}

uint32_t cinder_vk_program_create(const char *vs, const char *fs, const char **attribs, int n_attribs) {
  if (!D.dev || !vs || !*vs || !fs || !*fs || n_attribs < 0 || n_attribs > CINDER_VK_ATTRIBUTES ||
      (n_attribs && !attribs)) return native_reject();
  for (int i = 0; i < n_attribs; ++i) {
    if (!attribs[i] || !*attribs[i]) return native_reject();
    for (int j = 0; j < i; ++j) if (!strcmp(attribs[i], attribs[j])) return native_reject();
  }
  char key[17];
  snprintf(key, sizeof key, "%016llx", (unsigned long long)prog_key(vs, fs, attribs, n_attribs));
  const vkgl_spv *spv = NULL;
  for (int i = 0; i < VKGL_N_SPV; ++i) {
    if (VKGL_SPV[i].refl && !strncmp(VKGL_SPV[i].refl, key, 16)) { spv = &VKGL_SPV[i]; break; }
  }
  if (!spv || !native_object_reflection(spv->refl, key) ||
      !native_object_spirv(spv->vs, spv->n_vs) || !native_object_spirv(spv->fs, spv->n_fs) ||
      ((spv->n_vs2 || spv->n_fs2) && (!native_object_spirv(spv->vs2, spv->n_vs2) ||
                                                   !native_object_spirv(spv->fs2, spv->n_fs2)))) return native_reject();
  /* Build off-table: a failed reflection/module pair is never a drawable ID. */
  vprog p; memset(&p, 0, sizeof p);
  if (prog_reflect(&p, spv->refl) != 0) goto fail;
  free(p.shadow); p.shadow = NULL; p.dirty = 0;
  if (!native_object_uniforms(&p)) goto fail;
  p.vs = shader_module(spv->vs, (size_t)spv->n_vs);
  if (!p.vs) goto fail;
  p.fs = shader_module(spv->fs, (size_t)spv->n_fs);
  if (!p.fs) goto fail;
  if (spv->n_vs2) {
    p.vs2 = shader_module(spv->vs2, (size_t)spv->n_vs2);
    if (!p.vs2) goto fail;
    p.fs2 = shader_module(spv->fs2, (size_t)spv->n_fs2);
    if (!p.fs2) goto fail;
  }
  /* Pipeline keys outlive table handles. Never recycle a UID on counter wrap. */
  uint32_t uid = __atomic_load_n(&D.uid, __ATOMIC_RELAXED);
  do {
    if (uid == UINT32_MAX) goto fail;
  } while (!__atomic_compare_exchange_n(&D.uid, &uid, uid + 1, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED));
  p.uid = uid + 1;
  memcpy(p.key, key, sizeof p.key);
  uint32_t id = prog_gen();
  if (!id) goto fail;
  p.used = 1;
  *prog_get(id) = p;
  return id;
fail:
  native_object_program_free(&p);
  return native_reject();
}

int cinder_vk_program_ready(uint32_t id) {
  return native_program_valid(prog_get(id));
}

void cinder_vk_program_destroy(uint32_t id) {
  vprog *p = prog_get(id);
  if (!p) return;
  /* Created pipelines own compiled code, not shader modules or reflection.
   * Recorded items own their pipeline/layout handles and copied constants;
   * cache entries stay valid, keyed by the unrecycled program UID. */
  vprog old = *p;
  *p = (vprog){.used = 1};
  prog_release(id);
  native_object_program_free(&old);
}
