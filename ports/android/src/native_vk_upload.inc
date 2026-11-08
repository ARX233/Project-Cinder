/* Recoverable upload primitives. Included after native_vk.inc, before native
 * resources; shared ring/backing types are already defined by the executor. */
static uint8_t *native_ring_alloc(ring *r, VkDeviceSize size, VkDeviceSize align,
                                  VkBuffer *buffer, VkDeviceSize *offset) {
  if (!r || !buffer || !offset || !size || !align || size > PTRDIFF_MAX ||
      r->used > PTRDIFF_MAX || r->i > r->n || r->n > r->cap ||
      r->cap > SIZE_MAX / sizeof *r->b || (r->cap && !r->b)) return NULL;
  /* Scan with local cursors. Neither exhausted-buffer transitions nor failed
   * growth may consume the caller's current position. Positive alignments use
   * the same general (not merely power-of-two) rounding as the legacy ring. */
  size_t i = r->i;
  VkDeviceSize used = r->used;
  while (i < r->n) {
    vbufmem *b = r->b[i];
    if (!b || !b->buf || !b->map || b->size > PTRDIFF_MAX || used > b->size) return NULL;
    VkDeviceSize rem = used % align, pad = rem ? align - rem : 0;
    if (pad > UINT64_MAX - used) return NULL;
    VkDeviceSize off = used + pad;
    if (off <= b->size && size <= b->size - off) {
      r->i = i; r->used = off + size;
      *buffer = b->buf; *offset = off;
      return b->map + (size_t)off;
    }
    ++i; used = 0;
  }
  VkDeviceSize bytes = size > r->chunk ? size : r->chunk;
  if (bytes > PTRDIFF_MAX || r->n == SIZE_MAX) return NULL;
  size_t cap = r->cap;
  if (r->n == cap) {
    if (cap > SIZE_MAX / 2) return NULL;
    cap = cap ? cap * 2 : 64;
    if (cap > SIZE_MAX / sizeof *r->b) return NULL;
  }
  /* Allocate before growing the pointer table: if either allocation fails,
   * no backing/cursor/output is published. A successful realloc is the last
   * fallible step, so its moved pointer can be committed immediately. */
  vbufmem *b = bufmem_try_new(bytes, r->usage);
  if (!b) return NULL;
  if (!b->buf || !b->map || b->size != bytes) { bufmem_free(b); return NULL; }
  vbufmem **table = r->b;
  if (cap != r->cap) {
    table = realloc(r->b, cap * sizeof *table);
    if (!table) { bufmem_free(b); return NULL; }
  }
  table[r->n] = b;
  r->b = table; r->cap = cap; r->i = r->n; ++r->n; r->used = size;
  *buffer = b->buf; *offset = 0;
  return b->map;
}

static VkCommandBuffer native_up_cmd(uploader *u) {
  if (!u || !u->pool || !u->cmd) return VK_NULL_HANDLE;
  if (u->open) return u->cmd;
  VkCommandBufferBeginInfo begin = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
  begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
  if (vkBeginCommandBuffer(u->cmd, &begin) != VK_SUCCESS) return VK_NULL_HANDLE;
  u->open = 1;
  return u->cmd;
}
