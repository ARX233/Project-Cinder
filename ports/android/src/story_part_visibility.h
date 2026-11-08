/* Proposed WPK group contract for resource/render composition. These groups
 * retain EACH car/body's own original subtree and existing materials, not shared
 * attachment geometry. Existing color/vinyl/aero/wear groups are untouched. */
#ifndef STORY_PART_VISIBILITY_H
#define STORY_PART_VISIBILITY_H
#include "story_assembly.h"

enum {
  WPK_STORY_MUFFLER1=0x180, WPK_STORY_MUFFLER2=0x181,
  WPK_STORY_ROLLBAR=0x182,
  WPK_STORY_WINKER1=0x183, WPK_STORY_WINKER2=0x184,
  WPK_STORY_EMBLEM1=0x185, WPK_STORY_EMBLEM2=0x186,
  WPK_STORY_GLASS1=0x187, WPK_STORY_GLASS2=0x188, WPK_STORY_GLASS3=0x189,
  WPK_STORY_END=0x18a
};
/* -1 = not controlled by story assembly; 0 hidden; 1 visible. The render caller
 * provides permanent earned flags for THIS car/profile and resets after draw. */
static inline int story_part_visible(unsigned group, uint32_t flags) {
  if (group < WPK_STORY_MUFFLER1 || group >= WPK_STORY_END) return -1;
  if (group <= WPK_STORY_MUFFLER2)
    return group == WPK_STORY_MUFFLER1 + !!(flags & STORY_ASSEMBLY_MUFFLER);
  if (group == WPK_STORY_ROLLBAR) return !!(flags & STORY_ASSEMBLY_ROLL_CAGE);
  if (group <= WPK_STORY_WINKER2)
    return group == WPK_STORY_WINKER1 + !!(flags & STORY_ASSEMBLY_CLEAR_TAIL);
  if (group <= WPK_STORY_EMBLEM2)
    return group == WPK_STORY_EMBLEM1 + !!(flags & STORY_ASSEMBLY_GOLD_EMBLEM);
  unsigned glass = !(flags & STORY_ASSEMBLY_GLASS_SMOKE) ? 0u
                 : flags & STORY_ASSEMBLY_MACH_STICKER ? 2u : 1u;
  return group == WPK_STORY_GLASS1 + glass;
}
#endif
