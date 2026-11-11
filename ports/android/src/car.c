/* The race on the arcade's own code: CSeq::Init and CSeq::Exec, the arcade's race
 * sequence (the player's car, the traffic and what they hit), recompiled to C
 * (src/phys/phys_rc.c). This file sets the race up and reads back what to draw. */
#include "car.h"
#include "mileage_style.h"
#include "mathx.h"
#include "ghost_runtime.h"
#include "cardb.h"
#include "ghost_arcade_models.inc"
#include "ghost_arcade_palettes.inc"
#include "ghost_arcade_tyres.inc"

#include <math.h>
#include <float.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "phys/rc_runtime.h"

void f_89878c4(void); /* yt::CSeq::Init(SConfigPlay const&) */
/* Some old private physics translations omit End entirely. A weak no-op
 * definition makes those builds link; capture recognizes this stub and leaves
 * the old sequence ready. Patched full-root physics overrides it strongly. */
static int story_carry_end_stub_called;
__attribute__((weak, noinline)) void f_8986878(void) { story_carry_end_stub_called = 1; }
/* A legacy unpatched physics translation resolves this weak definition to 0.
 * The reviewed private bridge supplies the strong marker. Volatile prevents
 * compile-time folding of this link-time feature check. */
__attribute__((weak)) const volatile uint32_t rc_story_carry_bridge = 0;
void f_8983f64(void); /* yt::CSeq::Exec(std::auto_ptr<clGameInput> const&) */
void f_89ebd5c(void); /* yt::CLinx::CheckAck */
void f_89a2584(void); /* yt::CElapse::Init */
void f_89a2548(void); /* yt::CElapse::SetByMul */
void f_89825a8(void); /* yt::CSeq::GetInfoOtherCarDisp */
void f_89b45d0(void); /* yt::CMachine::GetInfoCarDisp */
void f_89b410c(void); /* yt::CMachine::GetInfoCarEffect */
#ifdef WMMT_EGL
#include <stdlib.h>
void f_89bcca8(void); /* yt::CMcPilot::Drive, for the desktop harness's WMMT_PILOT */
#endif
void f_89ba620(void); /* yt::CMachine::GetInfoCarCamera */
void f_8982580(void); /* yt::CSeq::GetInfoMirrorCamera */
void f_8982338(void); /* yt::CSeq::GetInfoCarCamera */
void f_89c4000(void); /* yt::CAreaProcessorBase::GetInfoJctBlockDisp */
void f_89c50c0(void); /* yt::CSlit::GetFirstPoint(float, float) const */
void f_89ba05c(void); /* yt::CMachine::SetFirstPos(SFirstPoint const&, float) */
void f_8983950(void); /* yt::CSeq::Get2DInfoRace */
void f_8983874(void); /* yt::CSeq::Get2DInfoMap */
void f_898380c(void); /* yt::CSeq::Get2DInfoSign */
/* Requires the expanded guarded physics recompile with these two roots. */
void f_8982f4c(void); /* Get2DInfoJctSelect: one 16-byte output */
void f_8983cd8(void); /* GetInfoJctDecideLine: three separate 12-byte outputs */
void f_898f518(void); /* yt::CSeq::GetInfoGoalLine */
void f_898f6d4(void); /* yt::CSeq::GetInfoSplitLine */
void f_8983e5c(void); /* yt::CSeq::GetInfoTenRivalLine */
void f_8983488(void); /* yt::CSeq::GetInfoRivalCarDisp */
void f_898287c(void); /* yt::CSeq::Get2DInfoStory */
void f_898317c(void); /* yt::CSeq::GetPlayResult */
/* Private Ghost variant supplies these exact original functions; old physics
 * stays link-compatible, but its zero feature marker fails closed. */
__attribute__((weak)) const volatile uint32_t rc_ghost_native_bridge = 0;
__attribute__((weak, noinline)) const char *rc_ghost_physics_id(void) { return NULL; }
__attribute__((weak, noinline)) void f_89924c8(void) { eax = 0; esp += 8; }
__attribute__((weak, noinline)) void f_8982d44(void) { eax = 0; esp += 4; }
void f_89e1130(void); /* CSampler::SamplingConfig(float seconds,int,int) */
void f_89e03e0(void); /* CSampler::SamplingStart(EStage,int seed) */
void f_89e12d4(void); /* CSampler::SetFileName */
void f_89e1320(void); /* CSampler::SetAreaPtAry */
void f_89e61dc(void); /* CSampler::Save */
void f_89e66ec(void); /* SSampleInfo070426::Reset */
void f_898332c(void); /* yt::CSeq::GetPlayLog(youTitle::_TitleRunningLog_ *) */
void f_858d8e8(void); /* youTitle::GetTitleList(_TitleData_ &, _TITLEDATALIST_ &) */
void f_899b378(void); /* yt::CConfigLoader::GetStorySeries(file, int, ESeries), returning SStorySeries */
void f_8982be8(void); /* yt::CSeq::Get2DInfoTenFight(S2DInfoTenFight *) */
void f_89923e4(void); /* yt::GetTenFightRaceField(EStage, level), returning SConfigRaceField */
/* YOURTMOVIE_CPP::clMovieSystem, the realtime movies (clRaceThread::initStory, race) */
void f_89fe784(void); /* clMovieSystem::clMovieSystem(unsigned int) */
void f_89fd9d0(void); /* clMovieSystem::Init(eMovieType, ECarType x4), returning the movie's length in frames */
void f_89fe890(void); /* clMovieSystem::UpDate(float frame) */
void f_89fde9c(void); /* clMovieSystem::GetRTMovieCamera(SInfoCarCamera *) */
void f_89fdfe8(void); /* clMovieSystem::GetRTMovieCarDisp(int, SInfoCarDisp *) */

/* arcade enums and data */
#define TRANS_AT 0u
#define TRANS_MT 1u
#define MODE_STORY 4u            /* EGameMode (GetEGameModeName) */
#define MODE_TIME_ATTACK 6u
/* SConfigPlay, what clRaceThread hands CSeq::Init */
#define CFG_CAR 0x00u
#define CFG_POWER 0x08u
#define CFG_HANDLING 0x0cu
#define CFG_TRANS 0x10u
#define CFG_STAGE 0x1cu
#define CFG_AREA 0x24u
#define CFG_DIST 0x28u
#define CFG_GOAL 0x2cu           /* the goal's odometer reading (SRaceField +0x10) */
#define CFG_MODE 0x34u
#define CFG_CARD 0x19u           /* a byte: the player has a card (clV386CardData::hasCard) */
#define CFG_LEVEL 0x38u          /* the story's loop (initStory: clWorkSpace +0x20, "lap") */
#define CFG_LOSSES 0x3cu         /* the episode's losses (clWorkSpace +0x24), easing the rivals */
#define CFG_RIVALS 0x44u         /* how many rivals (up to 3), then their ECharacter and ECarType */
#define CFG_RIVAL_CHAR 0x48u
#define CFG_RIVAL_CAR 0x54u
#define CFG_SERIES 0x40u         /* the story's ESeries (CSeq::Init: CConfigLoader::GetStorySeries) */
#define STORY_CONFIG 0x9433da8u  /* "data/carconfig/ytConfigStory.txt" */
#define RACE_FIELD 0x1cu         /* SConfigRaceField, 6 words: CFG_STAGE .. the goal and on */
#define CFG_TA_TRAFFIC 0xacu     /* clWorkSpace::isTaOtherCar: time attack with the traffic on */
#define CFG_TEN_LEVEL 0xb8u      /* the 10-in-a-row's level (clRaceThread::initTen: 10 = extend) */
#define MODE_TEN_FIGHT 7u        /* EGameMode of the 10-in-a-row */
/* CSeq's globals */
#define MACHINE_PTR 0x98028e4u   /* CMachine */
#define OTHER_GEN_PTR 0x9802894u /* COtherGen, the traffic */
#define LX_RIVALS 0x980289cu     /* yt::CLxRival *[3]: a versus' link cars (rivals 1..3) */
#define COUNTDOWN 0x9802a68u     /* CState: seconds of countdown left (Prep_CountDown sets 4) */
#define RACE_TIME_LEFT 0x9802a6cu
#define TIME_KEEPER_PTR 0x98028c8u /* CTimeKeeper, the checkpoints (the first is the start, the last the goal) */
#define TK_COUNT 0x00u           /* checkpoints */
#define TK_ODO 0x04u             /* float[]: the odometer reading of each (the last is the goal) */
#define TK_EXTEND 0x08u          /* float[]: seconds each one gives */
#define TK_SPLIT 0x10u           /* float[]: seconds since the start when each was passed */
#define TK_NEXT 0x14u            /* the next one to pass */
#define PLAY_VIEW 0x9802820u     /* CSeq's EPlayView (CSeq::GetInfoCarCamera hands it CMachine's) */
#define STATE 0x9802a78u         /* CState::GetStateName: 2 Run, 4 SlowDown, 5 StopWait, 6 TimeUp, 7 GoalWait, 8 Goal */
/* CSeq::Init gets the STireDimension from the display model here: a hook hands it the spec's */
#define TIRE_HOOK 0x898aa8du
#define TIRE_FRAME 0xd4u         /* the STireDimension at ebp - 0xd4 */
#define TEN_TIRE_HOOK 0x8985a4au   /* CSeq::Exec's next 10-in-a-row rival: CRivalSetting::GetSettingPt's 4th argument */
#define CUTIN_ON 0x9802970u      /* yt::CSeq::GetCutInInfoPt: the info at *CUTIN_INFO while set */
#define CUTIN_INFO 0x9802860u
#define TEN_RIVAL_NO 0x9802accu    /* CTenSeq: the rival on the road now, 0 the first */
#define RIVAL_TIRE_HOOK 0x898e699u /* and CRivalSetting::GetSettingPt the rival's, its 6th argument */
/* CMachine fields */
#define M_ENGINE 0x2c4u          /* CTransmission (engine state at +8: rad/s, AT flag at +0x34, gear at +0x3c) */
#define M_TURBO 0x340u           /* CTurbo (boost at +4) */
#define M_AREA_PROC 0x938u       /* CAreaProcessorBase*, followed by its SAreaProcessorInfo */
#define JCT_BLOCK_NAMES 0x93d9d00u /* const char* by junction block id (clCourseArrow) */
#define TA_LENGTHS 0x9778900u    /* GetTimeAttackRaceField: by EStage from 363, {u32 start, f32 length in mm} */
#define TA_STAGE0 363u

/* The time attack courses by course card, with the start each one gets from
 * GetConfigRaceField_TimeAttack(EStage): area and distance; and the arcade's course id
 * (nsMenuCheck::taCourseIDFromMenuOrder of the card's place: ids 5, 7 and 11 have no card). */
static const struct { uint32_t stage, area; float dist; int id; } COURSES[CAR_COURSES] = {
  { 363, 28, 1535000.0f, 0 },   /* TA_C1In: TkC1_In */
  { 364, 36, 2930000.0f, 1 },   /* TA_C1Out: TkGinza_Down */
  { 365, 44, 1095000.0f, 2 },   /* TA_RingLeft: TkN9_In */
  { 366, 37, 670000.0f, 3 },    /* TA_RingRight: TkGinza_Up */
  { 367, 45, 7220000.0f, 4 },   /* TA_WanganEast: TkN9_Out */
  { 369, 13, 1185000.0f, 6 },   /* TA_K1_Down: KgK1_Out */
  { 376, 64, 150000.0f, 8 },    /* NAGOYA: NkNagoya */
  { 371, 5, 5000.0f, 9 },       /* OSAKA: OsTonbori */
  { 377, 72, 11870000.0f, 14 }, /* FUKUOKA: FkFukuoka */
  { 372, 59, 390000.0f, 10 },   /* HAKONE_OUTWARD: HkHakone */
  { 374, 55, 3630000.0f, 12 },  /* SYUTOKO_TOKYO: TkTennouzu_Up */
  { 375, 56, 815000.0f, 13 },   /* SYUTOKO_KANAGAWA: TkTokyokou_Down */
};

int car_course_id(int course) { return course >= 0 && course < CAR_COURSES ? COURSES[course].id : 0; }
int car_course_ta_slot(int course) {
  return course >= 0 && course < CAR_COURSES && COURSES[course].stage - TA_STAGE0 < 15u ? (int)(COURSES[course].stage - TA_STAGE0) : -1;
}

/* EAreaId by city (the area names' prefixes): Os 1..9, Hk 58..61, Nk 62..69, Fk 70..73 */
int car_area_city(int area) {
  if (area >= 1 && area <= 9) return CAR_OSAKA;
  if (area >= 58 && area <= 61) return CAR_HAKONE;
  if (area >= 62 && area <= 69) return CAR_NAGOYA;
  if (area >= 70 && area <= 73) return CAR_FUKUOKA;
  return CAR_TOKYO;
}

int car_course_city(int course) { return course >= 0 && course < CAR_COURSES ? car_area_city((int)COURSES[course].area) : CAR_TOKYO; }

const car_spec CAR_SPEC_FD3S = { 5u, 5, { 690.0f, 298.3f, 1285.0f, 684.9f, 298.3f, -1065.2f }, 5, 24, 10 };

int car_tune_hp(int stock_hp, int power) {
  /* the table at 0x9736a60 (gauge_pow_to_Horse's too) */
  static const short HP[CAR_TUNE_MAX + 1] = { 0,   360, 400, 420, 450, 470, 500, 530, 550, 580, 600, 620, 640,
                                              660, 680, 700, 720, 740, 760, 780, 800, 810, 815, 820, 825 };
  if (power <= 0) return stock_hp;
  return HP[power > CAR_TUNE_MAX ? CAR_TUNE_MAX : power];
}

int car_tune_grade(int power, int handling) {
  int d = handling - power;
  return d <= -8 ? CAR_GRADE_DG : d <= -4 ? CAR_GRADE_D : d <= 3 ? CAR_GRADE_B : d <= 7 ? CAR_GRADE_G : CAR_GRADE_HG;
}

/* the traffic's ECarType (42..45) to its model */
static const int TRAFFIC_MODEL[4] = { CAR_TRAFFIC_RC2, CAR_TRAFFIC_NZE121, CAR_TRAFFIC_KZH100G, CAR_TRAFFIC_TRUCK };
#define TRAFFIC_TYPE0 42u
#define TRAFFIC_SLOT0 4 /* COtherGen's cars are 4..15 (0..3 the player and the rivals) */

static struct {
  char image[1024], config[1024];
  int course;
  car_spec spec;
  uint32_t m, gen, gin, gin_ptr, disp, eff, cam, mirror, jct, info_race, info_map, info_sign, lines, ten_line;
  uint32_t jct_select, jct_decide_line;
  int view;
  int ta_traffic, se_backfire_on;
  int manual, lever, top_lever; /* lever 0..gears-1, -1 = neutral */
  int traffic_model[CAR_TRAFFIC];
  int has_rival, n_rival;
  int ten_stage, ten_level; /* car_set_ten: the 10-in-a-row's EStage (0: not one) and level */
  int n_ten;
  uint32_t info_ten;
  car_rival ten[CAR_TEN_RIVALS];
  car_rival rival[CAR_RIVALS];
  /* car_set_versus: the link race's machines (vs_n others), ramp, km and seed */
  int vs_on, vs_pcb, vs_n, vs_ramp;
  int vs_race; /* the link's cars in the race now (0: not a versus) */
  mileage_style_log drive_style;
  float vs_km;
  unsigned vs_seed;
  car_link_car vs[CAR_LINK_MACHINES - 1];
  car_link_io vs_io;
  double vs_received[CAR_LINK_MACHINES]; /* monotonic seconds; 0 = no confirmed packet */
  uint32_t vs_count[CAR_LINK_MACHINES];
  unsigned char vs_count_valid[CAR_LINK_MACHINES];
  uint32_t info_story, result, first_pt, title_log;
  int ready;
} P = { .view = CAR_VIEW_BEHIND };

#define GHOST_TARGET_PTR 0x9802898u
#define GHOST_SAMPLER_PTR 0x9802880u
#define GHOST_TARGET_BYTES 0xb94u
#define GHOST_BRIDGE_MAGIC 0x47485331u
static struct {
  car_ghost_config config;
  car_ghost_observation observation;
  uint32_t info, recorder;
  int requested, started, saved, record_required;
  int arcade_on;
  int crown_race, finish_order, finish_sampled, first_crossing; /* +1 player first, -1 rival first */
  float finish_previous[2], finish_gap_m;
  car_ghost_arcade_binding arcade;
} PG;
static struct {
  uint64_t pending, token;
  uint32_t field[6], recorder;
  int saved;
} PT;
static int ghost_target_valid(void);
static void ghost_observe(void);

static uint32_t fbits(float v) { uint32_t u; memcpy(&u, &v, 4); return u; }

/* cdecl call into recompiled code, with arguments on the emulated stack */
static uint32_t call(void (*fn)(void), int n, ...) {
  uint32_t a[10];
  va_list ap;
  va_start(ap, n);
  for (int i = 0; i < n; i++) a[i] = va_arg(ap, uint32_t);
  va_end(ap);
  esp = RC_STACK_TOP - 0x1000 - 4 * n - 4;
  W32(esp, 0x20200000u);
  for (int i = 0; i < n; i++) W32(esp + 4 + 4 * i, a[i]);
  fn();
  return eax;
}

/* Private, in-memory equivalent of the original SCarryover serialization.
 * The game's 0x7c structure contains four image pointers. Those pointers are
 * never retained across rc_load_image: only verified unique area IDs are kept.
 * The bridge callbacks below replace the original file Save/Load entrypoints;
 * they do not open, create, read or write a carryover file. */
enum { STORY_CARRY_SIZE = 0x7c, STORY_CARRY_SLOTS = 4, STORY_AREA_COUNT = 75 };
#define STORY_AREA_TABLE 0x94429a0u
#define STORY_BRIDGE_MAGIC 0x53544331u
static struct {
  uint8_t data[STORY_CARRY_SIZE];
  int area[STORY_CARRY_SLOTS];
  car_rival rival[CAR_RIVALS];
  car_spec player;
  uint64_t token;
  uint32_t target_stage;
  int old_count, old_series, target_series, manual;
  int valid, armed, capturing, save_calls, initializing, loaded;
} story_carry;

static int carry_span(uint32_t address, uint32_t length) {
  return rc_mem && address >= RC_MEM_BASE && length <= RC_MEM_SIZE &&
         address - RC_MEM_BASE <= RC_MEM_SIZE - length;
}
/* The area's static image object supplies +0x20 (length), +0x24 (section
 * table) and +0x28 (section count) to CSlit::SetFirst/SearchSectionCur.
 * Reject heap/stack lookalikes and tables outside the immutable image. */
static int carry_image_span(uint32_t address, uint32_t length) {
  return rc_mem && address >= RC_IMG_BASE && length <= RC_IMG_END - RC_IMG_BASE &&
         address - RC_IMG_BASE <= RC_IMG_END - RC_IMG_BASE - length;
}
static int carry_area_valid(uint32_t address) {
  if (!carry_image_span(address, 0x2c)) return 0;
  uint32_t table = M32(address + 0x24), count = M32(address + 0x28);
  /* SearchSectionCur indexes 40-byte records and reads +0x28. */
  if (!count || count > (RC_IMG_END - RC_IMG_BASE - 4u) / 40u) return 0;
  return carry_image_span(table, count * 40u + 4u);
}
static uint32_t carry_word(const uint8_t *p) {
  uint32_t v; memcpy(&v, p, sizeof v); return v;
}
static void carry_put_word(uint8_t *p, uint32_t v) { memcpy(p, &v, sizeof v); }
static int carry_finite_word(const uint8_t *p) {
  float v; memcpy(&v, p, sizeof v); return isfinite(v);
}
static int carry_unique_rivals(const car_rival *r, int n) {
  if (!r || n < 1 || n > CAR_RIVALS) return 0;
  for (int i = 0; i < n; ++i) {
    if (r[i].character < 0) return 0;
    for (int j = 0; j < i; ++j)
      if (r[i].character == r[j].character) return 0;
  }
  return 1;
}
void car_story_carry_cancel(void) { memset(&story_carry, 0, sizeof story_carry); }

/* Generated code enters these with cdecl return address at esp and this at
 * esp+4. Emulate its return and AL success without invoking any file API. */
void rc_story_carry_save(void) {
  int ok = story_carry.capturing && ++story_carry.save_calls == 1;
  uint32_t address = 0;
  if (carry_span(esp, 8)) address = M32(esp + 4); else ok = 0;
  uint8_t tmp[STORY_CARRY_SIZE];
  int ids[STORY_CARRY_SLOTS] = { -1, -1, -1, -1 };
  if (!carry_span(address, STORY_CARRY_SIZE) ||
      !carry_span(STORY_AREA_TABLE, STORY_AREA_COUNT * 4u)) ok = 0;
  if (ok) {
    memcpy(tmp, VA(address), sizeof tmp);
    if (tmp[0x18] != 1) ok = 0; /* the player is mandatory */
    for (int k = 0; k < STORY_CARRY_SLOTS && ok; ++k) {
      unsigned flag = tmp[0x18 + k];
      if (flag > 1 || (k > story_carry.old_count && flag)) { ok = 0; break; }
      uint8_t *point = tmp + 0x1c + 0x14 * k;
      uint32_t old_pointer = carry_word(point + 4);
      if (flag) {
        int matches = 0;
        for (int i = 0; i < STORY_AREA_COUNT; ++i) {
          uint32_t candidate = M32(STORY_AREA_TABLE + 4u * (uint32_t)i);
          if (candidate && candidate == old_pointer) { ids[k] = i; ++matches; }
        }
        if (matches != 1 || !carry_area_valid(old_pointer)) ok = 0;
        /* SFirstPoint +0 is an integer word; only +8..+0x10 are
         * consumed as floating point by the original serializer. */
        for (int o = 8; o < 0x14 && ok; o += 4)
          if (!carry_finite_word(point + o)) ok = 0;
        if (!carry_finite_word(tmp + 0x6c + 4 * k)) ok = 0;
      }
      carry_put_word(point + 4, 0); /* discard every old image pointer */
    }
    for (int o = 4; o <= 0x10 && ok; o += 4)
      if (!carry_finite_word(tmp + o)) ok = 0;
    if (ok) {
      memcpy(story_carry.data, tmp, sizeof tmp);
      memcpy(story_carry.area, ids, sizeof ids);
    }
  }
  story_carry.valid = ok;
  eax = (eax & ~0xffu) | (ok ? 1u : 0u);
  esp += 4;
}

static int carry_target_matches(void) {
  if (!story_carry.valid || !story_carry.armed || !story_carry.token ||
      !story_carry.initializing || P.vs_on || P.ten_stage || !P.has_rival ||
      P.n_rival < story_carry.old_count || !carry_unique_rivals(P.rival, P.n_rival) ||
      P.rival[0].series != story_carry.target_series || P.spec.type != story_carry.player.type ||
      P.spec.gears != story_carry.player.gears || P.spec.spokes != story_carry.player.spokes ||
      P.manual != story_carry.manual ||
      memcmp(P.spec.tyres, story_carry.player.tyres, sizeof P.spec.tyres) != 0 ||
      carry_word(story_carry.data) != story_carry.target_stage) return 0;
  for (int k = 0; k < story_carry.old_count; ++k)
    if (story_carry.rival[k].character != P.rival[k].character ||
        story_carry.rival[k].type != P.rival[k].type ||
        story_carry.rival[k].level != P.rival[k].level) return 0;
  return 1;
}
void rc_story_carry_load(void) {
  uint32_t address = 0;
  int ok = carry_span(esp, 8);
  if (ok) address = M32(esp + 4);
  if (!carry_span(address, STORY_CARRY_SIZE) ||
      !carry_span(STORY_AREA_TABLE, STORY_AREA_COUNT * 4u) || !carry_target_matches()) ok = 0;
  uint8_t tmp[STORY_CARRY_SIZE];
  if (ok) {
    memcpy(tmp, story_carry.data, sizeof tmp);
    if (tmp[0x18] != 1) ok = 0;
    for (int k = 0; k < STORY_CARRY_SLOTS && ok; ++k) {
      unsigned flag = tmp[0x18 + k];
      if (flag > 1 || (k > story_carry.old_count && flag)) { ok = 0; break; }
      if (flag) {
        int id = story_carry.area[k];
        if (id < 0 || id >= STORY_AREA_COUNT) { ok = 0; break; }
        uint32_t pointer = M32(STORY_AREA_TABLE + 4u * (uint32_t)id);
        int matches = 0;
        for (int i = 0; i < STORY_AREA_COUNT; ++i)
          if (pointer && M32(STORY_AREA_TABLE + 4u * (uint32_t)i) == pointer) ++matches;
        if (matches != 1 || !carry_area_valid(pointer)) { ok = 0; break; }
        carry_put_word(tmp + 0x20 + 0x14 * k, pointer);
      }
    }
    /* One commit only, after all identity, stage, flag and area checks. */
    if (ok) memcpy(VA(address), tmp, sizeof tmp);
  }
  story_carry.loaded = ok;
  if (!ok && story_carry.initializing) car_story_carry_cancel();
  eax = (eax & ~0xffu) | (ok ? 1u : 0u);
  esp += 4;
}

int car_story_carry_capture(uint64_t token, int expected_series) {
  if (!token || story_carry.token || rc_story_carry_bridge != STORY_BRIDGE_MAGIC ||
      !P.ready || !P.has_rival || P.vs_race || P.vs_on || P.ten_stage ||
      !carry_span(STATE, 4) || M32(STATE) != 10 ||
      !carry_unique_rivals(P.rival, P.n_rival) || P.rival[0].series != expected_series) return -1;
  car_story_carry_cancel();
  story_carry.token = token;
  story_carry.old_count = P.n_rival;
  story_carry.old_series = expected_series;
  story_carry.player = P.spec;
  story_carry.manual = P.manual;
  memcpy(story_carry.rival, P.rival, sizeof story_carry.rival);
  story_carry.capturing = 1;
  /* Entering a real End tears down CSeq regardless of Save success. If an
   * incomplete translation resolves the weak stub, End was not entered. */
  story_carry_end_stub_called = 0;
  P.ready = 0;
  call(f_8986878, 0);
  story_carry.capturing = 0;
  if (story_carry_end_stub_called) {
    P.ready = 1;
    car_story_carry_cancel();
    return -1;
  }
  if (!story_carry.valid || story_carry.save_calls != 1) {
    car_story_carry_cancel();
    return 0;
  }
  return 1;
}
int car_story_carry_arm(uint64_t token, int target_series) {
  if (!token || !story_carry.valid || token != story_carry.token || target_series < 0 ||
      target_series == story_carry.old_series ||
      (story_carry.armed && target_series != story_carry.target_series)) {
    car_story_carry_cancel();
    return 0;
  }
  story_carry.armed = 1;
  story_carry.target_series = target_series;
  story_carry.loaded = 0;
  return 1;
}
int car_story_carry_loaded(uint64_t token) {
  return token && token == story_carry.token && story_carry.armed && story_carry.loaded;
}
int car_story_carry_finalize(uint64_t token) {
  if (!car_story_carry_loaded(token)) return 0;
  car_story_carry_cancel();
  return 1;
}

int car_init(const char *data_dir, char *err, int err_len) {
  snprintf(P.image, sizeof P.image, "%s/phys.img", data_dir);
  /* yt::CConfigLoader's files: data_dir/carconfig (the story's rivals, the 10-in-a-row) */
  snprintf(P.config, sizeof P.config, "%s", data_dir);
  rc_config_dir = P.config;
  FILE *f = fopen(P.image, "rb");
  if (!f) {
    snprintf(err, err_len, "cannot load %s", P.image);
    return -1;
  }
  fclose(f);
  return 0;
}

static int ghost_area_allowed(uint32_t id, void *context) {
  (void)context;
  if (id >= STORY_AREA_COUNT || !carry_image_span(STORY_AREA_TABLE + 4u * id, 4)) return 0;
  uint32_t area = M32(STORY_AREA_TABLE + 4u * id);
  return carry_area_valid(area) && M32(area) == id;
}
static int ghost_image(void) {
  return rc_mem || (P.image[0] && rc_load_image(P.image) == 0);
}
const char *car_ghost_physics_id(void) {
  return rc_ghost_native_bridge == GHOST_BRIDGE_MAGIC ? rc_ghost_physics_id() : NULL;
}
static int ghost_route_count(int ramp) {
  if (ramp < 1 || ramp > 22 || rc_ghost_native_bridge != GHOST_BRIDGE_MAGIC || !ghost_image()) return 0;
  int matches = 0;
  uint32_t count = 0;
  /* Original initTarget 0x88ff88b..89a reads frontend pointer table 0x9739140,
   * record+8 ERamp and record+0x14 routeCount before route/count division.
   * This is NOT yt::GetStage_FromRamp's weighted-stage array length. */
  for (uint32_t i = 0; i < CAR_LINK_RAMPS; ++i) {
    uint32_t record = M32(0x9739140u + 4u * i);
    if (!carry_image_span(record, 24)) return 0;
    if (M32(record + 8u) == (uint32_t)ramp) { ++matches; count = M32(record + 0x14u); }
  }
  return matches == 1 && count > 0u && count <= 64u ? (int)count : 0;
}
static int ghost_native_race_field(int ramp, int route, int tutorial, uint32_t output[6]) {
  if (output) memset(output, 0, 6u * sizeof *output);
  if (!output || rc_ghost_native_bridge != GHOST_BRIDGE_MAGIC || ramp < 1 || ramp > 22 ||
      route < 0 || (tutorial != 0 && tutorial != 1) || !ghost_image()) return 0;
  uint32_t count = (uint32_t)ghost_route_count(ramp);
  if (!count || count > 64u || (uint32_t)route >= count) return 0;
  uint32_t temporary = RC_STACK_TOP - 0x100u;
  memset(VA(temporary), 0xa5, 24);
  call(f_89924c8, 4, temporary, (uint32_t)ramp, fbits((float)route / (float)count), (uint32_t)tutorial);
  float start = MF(temporary + 12u), goal = MF(temporary + 16u);
  if (M32(temporary + 4u) || M32(temporary + 20u) || !ghost_area_allowed(M32(temporary + 8u), NULL) ||
      !isfinite(start) || !isfinite(goal) || goal <= start) return 0;
  memcpy(output, VA(temporary), 24);
  return 1;
}
int car_ghost_race_field(int ramp, int route, int tutorial, uint32_t output[6]) {
  /* Preserve the version-1 remote/qualification contract. Local shipped
   * records enter only through the separately checked arcade binding below. */
  if (output) memset(output, 0, 24);
  return route == 0 && ghost_native_race_field(ramp, route, tutorial, output);
}
static int ghost_field_supported(const uint32_t field[6], int tutorial) {
  uint32_t expected[6];
  for (int ramp = 1; ramp <= 22; ++ramp) {
    if (car_ghost_race_field(ramp, 0, tutorial, expected) && !memcmp(field, expected, 24)) return 1;
  }
  return 0;
}
int car_ghost_render_course(const uint32_t field[6]) {
  if (!field || rc_ghost_native_bridge != GHOST_BRIDGE_MAGIC || !ghost_image() ||
      (!ghost_field_supported(field, 0) && !ghost_field_supported(field, 1))) return -1;
  int city = car_area_city((int)field[2]);
  for (int course = 0; course < CAR_COURSES; ++course)
    if (car_course_city(course) == city) return course;
  return -1;
}
static int ghost_time_attack_field(int course, uint32_t field[6]) {
  if (course < 0 || course >= CAR_COURSES || !ghost_image()) return 0;
  uint32_t slot = COURSES[course].stage - TA_STAGE0;
  if (slot >= 15u || !carry_image_span(TA_LENGTHS + slot * 8u, 8u) ||
      !ghost_area_allowed(COURSES[course].area, NULL)) return 0;
  float start = COURSES[course].dist, length = MF(TA_LENGTHS + slot * 8u + 4u);
  if (!isfinite(length) || length <= 0.0f || !isfinite(start + length)) return 0;
  const uint32_t words[6] = {COURSES[course].stage, 0u, COURSES[course].area,
                             fbits(start), fbits(start + length), 0u};
  memcpy(field, words, sizeof words);
  return 1;
}
int car_ghost_time_attack_area(int course) {
  /* Original Ghost area order. The two multi-region Shuto TA courses use
   * the Wangan area, where their runs begin (Tennouzu/Tokyokou). */
  static const int areas[CAR_COURSES] = {0, 0, 1, 1, 2, 3, 4, 5, 7, 6, 2, 2};
  return course >= 0 && course < CAR_COURSES ? areas[course] : -1;
}
#include "car_ghost_arcade.inc"
#include "car_ghost_default.inc"

static int ghost_coverage(float first, float last, const uint32_t field[6]) {
  float start, goal;
  memcpy(&start, field + 3, 4); memcpy(&goal, field + 4, 4);
  return isfinite(first) && isfinite(last) && fabsf(first - start) <= 100000.0f &&
         last >= goal && last <= goal + 1000000.0f;
}
static int ghost_arcade_coverage(float first, float last, const uint32_t field[6]) {
  if (ghost_coverage(first, last, field)) return 1;
  uint32_t ids[GHOST_MAX_AREAS], count, kind;
  if (!ghost_stage_areas(field[0], ids, &count, &kind) || kind != 2u) return 0;
  for (uint32_t i = 0; i < count; ++i) if (ids[i] == field[2]) return 0;
  /* Original CSlit/straight-processor Init starts at path origin when the ramp
   * area precedes the selected finite StageAry path. The original raw field is
   * retained unchanged in SConfigPlay. These native stages really begin near
   * odo0 (observed initial machine555mm; original first samples1109..1110mm),
   * not raw ramp distance1450000mm. This is validation-only normalization. */
  uint32_t effective[6]; memcpy(effective, field, sizeof effective); effective[3] = fbits(0.0f);
  return ghost_coverage(first, last, effective);
}
static float ghost_goal_mm(const car_ghost_config *config) {
  float goal;
  memcpy(&goal, config->race_field + 4, sizeof goal);
  return goal;
}
int car_ghost_arcade_validate_trail(const car_ghost_arcade_binding *binding, const void *trail, size_t bytes) {
  ghost_format_policy policy;
  ghost_format_info info;
  return car_ghost_arcade_policy(binding,&policy) &&
    ghost_format_validate(trail,bytes,&policy,&info)==GHOST_FORMAT_OK &&
    ghost_arcade_coverage(info.first_odometer,info.last_odometer,binding->race_field);
}
void car_ghost_clear(void) {
  memset(&ghost_default, 0, sizeof ghost_default);
  if (PG.started) P.ready = 0;
  ghost_runtime_clear();
  memset(&PG, 0, sizeof PG);
  memset(&PT, 0, sizeof PT);
  memset(&ghost_arcade_policy_state, 0, sizeof ghost_arcade_policy_state);
}
static int ghost_prepare_config(const car_ghost_config *configuration, const car_ghost_arcade_binding *arcade) {
  car_ghost_config config;
  if (configuration) config = *configuration; else memset(&config, 0, sizeof config);
  car_ghost_clear();
  PG.observation = (car_ghost_observation){.status = CAR_GHOST_FAILED,
    .kind = config.kind == CAR_GHOST_CHALLENGE || config.kind == CAR_GHOST_QUALIFICATION ? config.kind : 0,
    .session_token = config.session_token}; /* rejected requests cannot fall into TA */
  PG.requested = 1;
  P.ready = 0; /* a rejected Ghost request cannot keep driving a stale ordinary race */
  if (!configuration || config.abi_version != CAR_GHOST_ABI_VERSION || !config.session_token ||
      rc_ghost_native_bridge != GHOST_BRIDGE_MAGIC || !car_ghost_physics_id() || !ghost_image() ||
      (config.kind != CAR_GHOST_CHALLENGE && config.kind != CAR_GHOST_QUALIFICATION) ||
      (config.record_player != 0 && config.record_player != 1) ||
      config.native_flags[0] > 1 || config.native_flags[1] > 1 ||
      (!arcade && !ghost_field_supported(config.race_field, config.native_flags[1]))) return 0;
  ghost_format_policy policy = {.stage=config.race_field[0], .area_allowed=ghost_area_allowed};
  if (arcade && (config.kind != CAR_GHOST_CHALLENGE || config.record_player ||
      memcmp(config.race_field, arcade->race_field, 24) ||
      !car_ghost_arcade_policy(arcade, &policy))) return 0;
  if (config.kind == CAR_GHOST_CHALLENGE) {
    if (config.trail_band[0] != config.rival.power || config.trail_band[1] != config.rival.handling ||
        config.rival.power < 0 || config.rival.power > CAR_TUNE_MAX ||
        config.rival.handling < 0 || config.rival.handling > CAR_TUNE_MAX ||
        config.rival.power + config.rival.handling > CAR_TUNE_TOTAL ||
        config.trail_band[2] < 0 || config.trail_band[2] > 876000 ||
        (!arcade && config.rival.type >= TRAFFIC_TYPE0) || (arcade && config.rival.type > 44u) ||
        config.rival.gears < 4 || config.rival.gears > 6 || config.rival.spokes < (arcade ? 0 : 1) || config.rival.spokes > 64)
      return 0;
    for (int i = 0; i < 6; ++i)
      if (!isfinite(config.rival.tyres[i]) || fabsf(config.rival.tyres[i]) > 10000.0f) return 0;
    if (config.rival.tyres[1] <= 0 || config.rival.tyres[4] <= 0 ||
        ghost_runtime_prepare(config.trail, config.trail_bytes, &policy) != GHOST_FORMAT_OK) return 0;
    const ghost_format_info *info = ghost_runtime_input_info();
    if (!info || !(arcade ? ghost_arcade_coverage(info->first_odometer, info->last_odometer, config.race_field) :
                           ghost_coverage(info->first_odometer, info->last_odometer, config.race_field))) {
      ghost_runtime_clear(); return 0;
    }
  } else {
    /* Qualification is explicitly solo mode 6 + native sampler, never mode 9
     * (Tournament), and never an automatic missing-opponent fallback. */
    if (!config.record_player || config.trail || config.trail_bytes) return 0;
  }
  PG.config = config;
  PG.record_required = config.kind == CAR_GHOST_QUALIFICATION || config.record_player;
  PG.config.trail = NULL; /* validated runtime owns the immutable copy */
  PG.arcade_on = arcade != NULL;
  if (arcade) PG.arcade = *arcade;
  PG.observation = (car_ghost_observation){.status = CAR_GHOST_PREPARED, .kind = config.kind,
                                         .session_token = config.session_token};
  P.has_rival = P.n_rival = P.vs_on = P.ten_stage = P.n_ten = 0;
  car_story_carry_cancel();
  return 1;
}
int car_ghost_prepare(const car_ghost_config *config) {
  return ghost_prepare_config(config, NULL);
}
int car_ghost_arcade_prepare(const car_ghost_arcade_spec *spec, car_ghost_arcade_binding *binding) {
  car_ghost_arcade_binding local;
  if (binding) memset(binding, 0, sizeof *binding);
  if (!spec || !spec->session_token || !car_ghost_arcade_bind(spec, &local)) {
    car_ghost_config rejected = {.abi_version=CAR_GHOST_ABI_VERSION, .kind=CAR_GHOST_CHALLENGE,
                                .session_token=spec ? spec->session_token : 0};
    ghost_prepare_config(&rejected, NULL); /* clears readiness; cannot fall back */
    return 0;
  }
  car_ghost_config config = {.abi_version=CAR_GHOST_ABI_VERSION, .session_token=spec->session_token,
    .kind=CAR_GHOST_CHALLENGE, .rival=local.rival, .trail=spec->trail, .trail_bytes=spec->trail_bytes,
    .trail_band={spec->power, spec->handling, spec->age_hours},
    .native_flags={(unsigned char)spec->has_crown, (unsigned char)spec->first_tutorial}};
  memcpy(config.race_field, local.race_field, sizeof config.race_field);
  if (!ghost_prepare_config(&config, &local)) return 0;
  if (local.raw_ramp >= CAR_GHOST_TA_RAMP_BASE)
    car_ghost_arm_rival_runout(spec->session_token);
  if (binding) *binding = local;
  return 1;
}
int car_ghost_arcade_info(car_ghost_arcade_binding *binding) {
  if (binding) memset(binding, 0, sizeof *binding);
  if (!binding || !PG.arcade_on || PG.config.kind != CAR_GHOST_CHALLENGE || PG.observation.status == CAR_GHOST_FAILED) return 0;
  *binding = PG.arcade;
  return 1;
}
int car_ghost_crown_area_matches(unsigned area,int raw_ramp) {
  return area<8u && raw_ramp>=0 && raw_ramp<CAR_LINK_RAMPS && ghost_image() &&
    ghost_default_area_ramp(area,raw_ramp);
}
int car_ghost_arm_cloud_recording(uint64_t token) {
  if (!token || !PG.arcade_on || PG.config.session_token!=token ||
      PG.observation.status!=CAR_GHOST_PREPARED) return 0;
  PG.config.record_player=1;
  return 1;
}
int car_ghost_arm_time_attack_recording(uint64_t token) {
  if (!token || PG.requested || !car_ghost_physics_id()) return 0;
  PT.pending = token;
  return 1;
}
int car_ghost_arm_local_crown(uint64_t token, int record_player) {
  if (!token || !PG.arcade_on || !PG.config.native_flags[0] || PG.config.session_token != token ||
      PG.observation.status != CAR_GHOST_PREPARED) return 0;
  if (PG.config.kind == CAR_GHOST_CHALLENGE) car_ghost_arm_rival_runout(token);
  PG.finish_order = 1;
  PG.crown_race = 1;
  if (record_player) PG.config.record_player = PG.record_required = 1;
  return 1;
}
int car_ghost_arm_rival_runout(uint64_t token) {
  if (!token || !PG.arcade_on || PG.config.kind != CAR_GHOST_CHALLENGE ||
      PG.config.session_token != token || PG.observation.status != CAR_GHOST_PREPARED) return 0;
  if (!PG.finish_order) ghost_runtime_extend_crown(ghost_goal_mm(&PG.config), CAR_GHOST_CROWN_RUNOUT_TICKS);
  PG.finish_order = 1;
  return 1;
}
static int ghost_target_valid(void) {
  if (!PG.started || PG.config.kind != CAR_GHOST_CHALLENGE || !rc_mem) return 0;
  uint32_t target = M32(GHOST_TARGET_PTR);
  const ghost_format_info *info = ghost_runtime_input_info();
  if (!info || target < RC_HEAP_BASE || !carry_span(target, GHOST_TARGET_BYTES) ||
      M32(target + 4u) != GHOST_NATIVE_VERSION || M32(target + 0x10u) != info->samples ||
      M32(target + 0x1cu) != info->stage || M32(target + 0x20u) != info->seed ||
      M32(target + 0x28u) != info->sample_step) return 0;
  uint32_t samples = M32(target + 8u), areas = M32(target + 0x14u), count = M32(target + 0x18u);
  if (samples < RC_HEAP_BASE || !carry_span(samples, info->samples * GHOST_SAMPLE_BYTES) ||
      count != info->areas || areas < RC_HEAP_BASE || !carry_span(areas, (count + 1u) * 4u)) return 0;
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t area = M32(areas + 4u * i);
    uint32_t expected;
    if (!carry_area_valid(area) || !ghost_area_allowed(M32(area), NULL) ||
        !ghost_runtime_input_area(i, &expected) || M32(area) != expected) return 0;
  }
  if (M32(areas + count * 4u)) return 0;
  return isfinite(MF(target + 0x484u));
}
static void ghost_observe_crossing(float player, float rival) {
  float goal = ghost_goal_mm(&PG.config);
  if (PG.first_crossing || !isfinite(player) || !isfinite(rival)) return;
  if (player >= goal || rival >= goal) {
    float gap = player - rival;
    if (PG.finish_sampled) {
      /* Interpolate within this tick so an overtake just beyond the line
       * cannot reverse the order when both odometers cross in one tick. */
      float p0 = PG.finish_previous[0], r0 = PG.finish_previous[1];
      float player_at = player >= goal ? (goal - p0) / (player - p0) : INFINITY;
      float rival_at = rival >= goal ? (goal - r0) / (rival - r0) : INFINITY;
      float first = fminf(player_at, rival_at);
      gap = player_at <= rival_at ?
        (goal - r0) - first * (rival - r0) :
        first * (player - p0) - (goal - p0);
      PG.first_crossing = player_at <= rival_at ? 1 : -1;
    } else PG.first_crossing = gap >= 0.0f ? 1 : -1;
    PG.finish_gap_m = gap * 0.001f;
    return;
  }
  PG.finish_previous[0] = player;
  PG.finish_previous[1] = rival;
  PG.finish_sampled = 1;
}

static int ghost_crown_running_out(void) {
  return PG.crown_race && PG.observation.goal_reached &&
    PG.observation.native_ticks - PG.observation.finish_tick < CAR_GHOST_CROWN_RUNOUT_TICKS;
}

static int ghost_recorder_valid(uint32_t recorder, uint32_t stage) {
  if (recorder < RC_HEAP_BASE || !carry_span(recorder, 0x64)) return 0;
  uint32_t capacity = M32(recorder + 0xcu), step = M32(recorder + 0x28u);
  return capacity >= 2u && capacity <= GHOST_MAX_SAMPLES &&
         (step == 3u || step == 5u || (stage == GHOST_LONG_TA_STAGE && step == 9u)) &&
         M32(recorder + 0x1cu) == stage && carry_span(M32(recorder + 8u), capacity * GHOST_SAMPLE_BYTES);
}
static int ghost_extend_ta_recorder(uint32_t recorder, uint32_t stage) {
  if (!ghost_recorder_valid(recorder, stage) || M32(recorder + 0x10u)) return 0;
  /* The stock 270-second buffer truncates longer Time Attack courses.
   * Native SamplingConfig supports longer intervals while retaining the
   * 8192 sample limit. Shuto Tokyo needs a larger window for its 60 km. */
  uint32_t ticks = stage == GHOST_LONG_TA_STAGE ? GHOST_LONG_TA_MAX_TICKS : GHOST_MAX_TICKS;
  uint32_t step = stage == GHOST_LONG_TA_STAGE ? 9u : 5u;
  uint32_t bytes = (ticks / step + 1u) * GHOST_SAMPLE_BYTES;
  uint32_t aligned = (rc_heap_next + 15u) & ~15u;
  if (aligned > RC_HEAP_BASE + RC_HEAP_SIZE - bytes) return 0;
  call(f_89e1130, 4, recorder, fbits((float)ticks / 60.0f), step, 1u);
  return ghost_recorder_valid(recorder, stage) && M32(recorder + 0x28u) == step;
}
static int ghost_recorder_covers(uint32_t recorder, const uint32_t field[6], int arcade) {
  if (!ghost_recorder_valid(recorder, field[0])) return 0;
  uint32_t count = M32(recorder + 0x10u), samples = M32(recorder + 8u);
  return count >= 2u && count <= M32(recorder + 0xcu) &&
    (arcade ? ghost_arcade_coverage : ghost_coverage)(
      MF(samples), MF(samples + (count - 1u) * GHOST_SAMPLE_BYTES), field);
}
static int ghost_recorder_save(uint32_t recorder) {
  W8(recorder + 0x30u, 0);
  call(f_89e1320, 1, recorder);
  if (!call(f_89e61dc, 1, recorder)) return 0;
  ghost_runtime_stop();
  return 1;
}
static void ghost_configure_recording(uint32_t cfg) {
  uint32_t output_name = rc_alloc(sizeof GHOST_OUTPUT_TOKEN);
  memcpy(VA(output_name), GHOST_OUTPUT_TOKEN, sizeof GHOST_OUTPUT_TOKEN);
  W32(cfg + 0x11cu, output_name);
  /* Original CSeq stores (cfg+0x118)^1 into sampling selector 0x9802964;
   * Exec samples only selector 0/2. Explicit recording uses selector 0. */
  W8(cfg + 0x118u, 1);
}
static void ghost_begin_ta_recording(uint32_t cfg, uint64_t token) {
  int raw_ramp = CAR_GHOST_TA_RAMP_BASE + P.course;
  car_ghost_arcade_binding b = {.source_id=token, .raw_ramp=raw_ramp, .ramp=raw_ramp + 1, .route_count=1};
  ghost_format_policy policy;
  if (!ghost_time_attack_field(P.course, b.race_field) ||
      memcmp(VA(cfg + RACE_FIELD), b.race_field, sizeof b.race_field) ||
      !car_ghost_arcade_policy(&b, &policy) || !ghost_runtime_begin_qualification(&policy)) return;
  memcpy(PT.field, b.race_field, sizeof PT.field);
  PT.token = token;
  ghost_configure_recording(cfg);
}
int car_ghost_time_attack_recording_info(uint64_t token, int *course, uint32_t field[6], car_spec *owner) {
  car_ta_ranking_observation native;
  if (!token || PT.token != token || !course || !field || !owner ||
      !car_ta_ranking_info(&native) || !native.goal ||
      memcmp(native.race_field, PT.field, sizeof PT.field) ||
      (!PT.saved && !ghost_recorder_covers(PT.recorder, PT.field, 0))) return 0;
  *course = native.course;
  memcpy(field, PT.field, sizeof PT.field);
  *owner = native.owner;
  return 1;
}
int car_ghost_time_attack_recording_export(uint64_t token, void *output, size_t capacity, size_t *bytes) {
  if (!bytes) return 0;
  *bytes = 0;
  int course;
  uint32_t field[6];
  car_spec owner;
  if (!car_ghost_time_attack_recording_info(token, &course, field, &owner)) return 0;
  if (!PT.saved) {
    if (!ghost_recorder_save(PT.recorder)) return 0;
    PT.saved = 1;
  }
  return ghost_runtime_export(output, capacity, bytes, NULL);
}

static void ghost_observe(void) {
  if (!PG.started || PG.observation.status == CAR_GHOST_FAILED || !P.ready) return;
  if (PG.config.kind == CAR_GHOST_DEFAULT) {
    PG.observation.native_default_ai_valid = ghost_default_ai_valid();
    if (!PG.observation.native_default_ai_valid) { PG.observation.status = CAR_GHOST_FAILED; P.ready = 0; return; }
  }
  if (PG.config.kind == CAR_GHOST_CHALLENGE) {
    PG.observation.native_target_valid = ghost_target_valid();
    if (!PG.observation.native_target_valid) {
      PG.observation.status = CAR_GHOST_FAILED;
      ghost_runtime_stop();
      P.ready = 0;
      return;
    }
  }
  /* Get2DInfoTarget reads the native CTarget odometer or the original default
   * AI odometer (0x8982da0), depending on which target owns this race. */
  uint32_t state = M32(STATE);
  PG.observation.live_gap_mm = NAN;
  if (!PG.observation.result_valid && (PG.config.kind==CAR_GHOST_CHALLENGE || PG.config.kind==CAR_GHOST_DEFAULT)) {
    WF(PG.info + 4u, NAN);
    if (call(f_8982d44, 1, PG.info) && isfinite(MF(PG.info + 4u))) {
      PG.observation.live_gap_mm = MF(PG.info + 4u);
      PG.observation.gap_m = PG.observation.live_gap_mm * 0.001f;
      if (PG.finish_order && (state == 2u || state == 7u || state == 8u)) {
        float rival = PG.config.kind == CAR_GHOST_CHALLENGE ? MF(M32(GHOST_TARGET_PTR) + 0x484u) :
                                                           MF(M32(0x98028b4u) + 0x7f4u);
        ghost_observe_crossing(MF(P.m + 0x970u), rival);
      }
    }
  }
  if (!PG.observation.result_valid && (state == 3 || state == 6 || state == 8)) {
    memset(VA(P.result), 0xff, 0x40);
    uint32_t result_ok = call(f_898317c, 1, P.result);
    uint32_t place = M32(P.result);
    unsigned goal = M8(P.result + 0x10u);
    if (result_ok && place <= 1u && goal <= 1u) {
      PG.observation.result_valid = 1;
      /* Target's result console reads the frozen GetPlayResult advantage,
       * distinct from the live Get2DInfoTarget odometer difference. */
      float result_gap = MF(P.result + 8u);
      if (isfinite(result_gap)) PG.observation.gap_m = result_gap * 0.001f;
      PG.observation.place = (int)place;
      PG.observation.goal_reached = (int)goal;
      if (state == 8 && goal && PG.first_crossing) {
        PG.observation.place = PG.first_crossing < 0;
        PG.observation.gap_m = PG.finish_gap_m;
      }
      PG.observation.won = state == 8 && PG.observation.place == 0 && goal;
      PG.observation.status = CAR_GHOST_FINISHED;
      PG.observation.finish_tick=PG.observation.native_ticks;
    }
  }
  PG.observation.recording = ghost_runtime_recording();
  if (!PG.saved && PG.config.record_player && PG.recorder && PG.observation.status == CAR_GHOST_FINISHED &&
      PG.observation.result_valid && PG.observation.goal_reached &&
      !(PG.observation.won && ghost_crown_running_out())) {
    PG.observation.export_ready = ghost_recorder_covers(PG.recorder, PG.config.race_field, PG.arcade_on);
  }
}
int car_ghost_status(car_ghost_observation *observation) {
  if (!observation) return 0;
  ghost_observe();
  PG.observation.recording = ghost_runtime_recording();
  if (PG.observation.status == CAR_GHOST_FAILED) PG.observation.export_ready = 0;
  *observation = PG.observation;
  return PG.observation.status != CAR_GHOST_OFF;
}
int car_ghost_export(void *output, size_t capacity, size_t *bytes) {
  if (bytes) *bytes = 0;
  ghost_observe();
  if (!bytes || !PG.started || !PG.config.record_player || PG.observation.status != CAR_GHOST_FINISHED ||
      !PG.observation.result_valid || !PG.observation.goal_reached || !PG.recorder ||
      (PG.observation.won && ghost_crown_running_out())) return 0;
  if (!PG.saved) {
    if (!ghost_recorder_covers(PG.recorder, PG.config.race_field, PG.arcade_on) ||
        !ghost_recorder_save(PG.recorder)) return 0;
    PG.saved = 1;
    PG.observation.recording = 0;
  }
  int ok = ghost_runtime_export(output, capacity, bytes, NULL);
  PG.observation.export_ready = ok || *bytes > 0;
  return ok;
}

/* CSeq::Init: STireDimension, normally from the display model: front (x, radius, z), rear, spokes; mm */
static void on_hook(uint32_t at) {
  if (at == 0x898f18du && PG.requested && PG.config.kind == CAR_GHOST_DEFAULT) {
    ++ghost_default.tire_hook_calls;
    uint32_t tire = ebp - 0xb8u, cfg = M32(0x9802968u);
    int valid = ghost_default.active && ghost_default.tire_hook_calls == 1 &&
      carry_span(esp, 0x2cu) && tire >= RC_STACK_TOP - RC_STACK_SIZE && carry_span(tire, 0x1cu) &&
      M32(esp + 0x10u) == tire && carry_span(cfg, 0xd2u) && M32(cfg + CFG_MODE) == 8u &&
      M32(cfg + 0xccu) == 0u && M32(cfg + 0xbcu) == PG.config.rival.type &&
      M32(esp + 0xcu) == PG.config.rival.type &&
      (PG.config.record_player?ghost_runtime_recording():!ghost_runtime_active());
    ghost_default.tire_hook_valid = valid;
    if (valid) {
      for (int i = 0; i < 6; ++i) WF(tire + 4u * (uint32_t)i, PG.config.rival.tyres[i]);
      W32(tire + 0x18u, (uint32_t)PG.config.rival.spokes);
    }
    return;
  }
  if (at == 0x898807eu && PG.requested && PG.config.kind == CAR_GHOST_CHALLENGE) {
    uint32_t tire = ebp - 0xb8u;
    for (int i = 0; i < 6; ++i) WF(tire + 4u * (uint32_t)i, PG.config.rival.tyres[i]);
    W32(tire + 0x18u, (uint32_t)PG.config.rival.spokes);
    return;
  }
  if (at == 0x898484cu && PG.started && PG.observation.native_target_valid) {
    PG.observation.collision_registrations++;
    return;
  }
  if (at == RIVAL_TIRE_HOOK) { /* CSeq::Init's loop over the rivals: edi the rival's number */
    const car_rival *r = &P.rival[edi >= 1 && edi <= (uint32_t)P.n_rival ? edi - 1 : 0];
    uint32_t tire = M32(esp + 0x14);
    for (int i = 0; i < 6; i++) WF(tire + 4 * i, r->tyres[i]);
    W32(tire + 0x18, (uint32_t)r->spokes);
    return;
  }
  if (at == TEN_TIRE_HOOK) {
    uint32_t k = M32(TEN_RIVAL_NO);
    if (k >= (uint32_t)P.n_ten) return;
    uint32_t tire = M32(esp + 0xc);
    for (int i = 0; i < 6; i++) WF(tire + 4 * i, P.ten[k].tyres[i]);
    W32(tire + 0x18, (uint32_t)P.ten[k].spokes);
    return;
  }
  if (at != TIRE_HOOK) return;
  uint32_t tire = ebp - TIRE_FRAME;
  for (int i = 0; i < 6; i++) WF(tire + 4 * i, P.spec.tyres[i]);
  W32(tire + 0x18, (uint32_t)P.spec.spokes);
  /* the cars after it, 0x1c apart (ebp-0xb8, -0x9c, -0x80): yt::GetTireDimension's for cars 1..3
   * (clCarDispManager::getRivalTireParam, the display side's). The realtime movies' ghosts take
   * them (the loop at 0x898bc15: CGhostSetting::GetSettingPt with car i's); unset, their tyres
   * stood nowhere (NaN) */
  for (int k = 0; k < P.n_rival && k < 3; ++k) {
    uint32_t t = tire + 0x1cu * (uint32_t)(k + 1);
    for (int i = 0; i < 6; i++) WF(t + 4 * i, P.rival[k].tyres[i]);
    W32(t + 0x18, (uint32_t)P.rival[k].spokes);
  }
  /* in a versus the link's cars (CSeq::Init's loop at 0x898e800: yt::CLxRivalSetting::GetSettingPt
   * with car k + 1's) */
  for (int k = 0; P.vs_on && k < P.vs_n; ++k) {
    uint32_t t = tire + 0x1cu * (uint32_t)(k + 1);
    for (int i = 0; i < 6; i++) WF(t + 4 * i, P.vs[k].tyres[i]);
    W32(t + 0x18, (uint32_t)P.vs[k].spokes);
  }
}

void car_set_ta_traffic(int on) { P.ta_traffic = on != 0; }

void car_set_rivals(const car_rival *rivals, int n) {
  P.n_rival = n < 0 ? 0 : n > CAR_RIVALS ? CAR_RIVALS : n;
  P.has_rival = P.n_rival > 0;
  for (int i = 0; i < P.n_rival; ++i) P.rival[i] = rivals[i];
}

void car_set_ten(int stage, int level, const car_rival *rivals, int n) {
  P.ten_stage = stage;
  P.ten_level = level;
  P.n_ten = n < 0 ? 0 : n > CAR_TEN_RIVALS ? CAR_TEN_RIVALS : n;
  for (int i = 0; i < P.n_ten; ++i) P.ten[i] = rivals[i];
}

/* The versus race. clRaceThread::initJoin fills SConfigPlay's link part: +0x60 the join's
 * NoRubberBand, +0x64 this machine's place among the joined (its PCB id's), +0x68 how many others,
 * then per other machine i: +0x6c its PCB id, +0x78 its place, +0x84 its ECarType (from its card),
 * +0x90 / +0x9c its power and handling tune, and +0xa8 the race's random number; the start from
 * GetConfigRaceField_Battle(ERamp of the join ramp: table 0x9739140, +8) and the goal its distance
 * on (clNet::getJoinDist km). CSeq::Init then has CLinx::Init(+0x64, +0x68, +0x6c, +0x78). */
#define MODE_BATTLE 5u
#define CFG_LINK_NO_BAND 0x60u
#define CFG_LINK_PLACE 0x64u
#define CFG_LINK_OTHERS 0x68u
#define CFG_LINK_PCB 0x6cu
#define CFG_LINK_OTHER_PLACE 0x78u
#define CFG_LINK_CAR 0x84u
#define CFG_LINK_POWER 0x90u
#define CFG_LINK_HANDLING 0x9cu
#define CFG_LINK_RANDOM 0xa8u
#define JOIN_RAMPS 0x9739140u /* the join ramps: {name, course, ERamp, ...} */
#define LINK_BUF 0x400u       /* clNet's race packet buffers */
void f_8992604(void); /* yt::GetBattleRaceField(ERamp) */

void car_set_versus(int pcb, const car_link_car *others, int n, int ramp, float km, unsigned seed, const car_link_io *io) {
  /* Invalidate observations as soon as a new session is configured. */
  memset(P.vs_received, 0, sizeof P.vs_received);
  memset(P.vs_count_valid, 0, sizeof P.vs_count_valid);
  P.vs_race = 0;
  P.vs_on = n > 0 && io;
  P.vs_pcb = pcb;
  P.vs_n = n < 0 ? 0 : n > CAR_LINK_MACHINES - 1 ? CAR_LINK_MACHINES - 1 : n;
  for (int i = 0; i < P.vs_n; ++i) P.vs[i] = others[i];
  P.vs_ramp = ramp < 0 || ramp >= CAR_LINK_RAMPS ? 0 : ramp;
  P.vs_km = km;
  P.vs_seed = seed;
  if (io) P.vs_io = *io;
}

const char *car_link_ramp_name(int ramp) {
  if (ramp < 0 || ramp >= CAR_LINK_RAMPS || !P.ready) return "";
  return (const char *)VA(M32(M32(JOIN_RAMPS + 4u * (uint32_t)ramp)));
}

/* clNet::receiveRacePacket / sendRacePacket, the port's */
static void link_receive(void) { if (P.vs_io.receive) P.vs_io.receive(P.vs_io.ctx); }
static void link_send(void) { if (P.vs_io.send) P.vs_io.send(VA(rc_link_tx), CAR_LINK_PACKET, P.vs_io.ctx); }

/* A conservative port timeout, not an asserted arcade constant. The transport
 * must call this only for a room/race/PCB/sequence-validated new packet. */
static double link_now(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return 0;
  return (double)t.tv_sec + (double)t.tv_nsec / 1000000000.0;
}
int car_link_time_fresh(double now, double received) {
  return isfinite(now) && isfinite(received) && received > 0 && now >= received && now - received <= 1.0;
}
void car_link_fresh(int pcb, int active) {
  if (pcb < 0 || pcb >= CAR_LINK_MACHINES) return;
  P.vs_received[pcb] = active ? link_now() : 0;
}
int car_link_observation_fresh(int pcb, double observed) {
  return pcb >= 0 && pcb < CAR_LINK_MACHINES && observed == P.vs_received[pcb] &&
         car_link_time_fresh(link_now(), observed);
}

void car_link_deliver(int pcb, const unsigned char *packet, int len) {
  if (!rc_link_rx || !packet || pcb < 0 || pcb >= CAR_LINK_MACHINES || len < CAR_LINK_PACKET) return;
  unsigned char *destination = VA(rc_link_rx + LINK_BUF * (uint32_t)pcb);
  int matched = 0;
  if (P.ready && pcb != P.vs_pcb)
    for (int i = 0; i < P.vs_race; ++i) if (P.vs[i].pcb == pcb) matched = 1;
  if (!matched) {
    /* Preserve receive semantics even during Init or for an unrelated PCB. */
    memcpy(destination, packet, CAR_LINK_PACKET);
    return;
  }
  /* Transport calls this for newly delivered, race-validated packets, but WV1
   * also delivers duplicate frame counts. Do not extend the HUD freshness on
   * duplicates or old frames. Keep the original packet delivery semantics. */
  uint32_t count = (uint32_t)packet[0x34] | (uint32_t)packet[0x35] << 8 |
                   (uint32_t)packet[0x36] << 16 | (uint32_t)packet[0x37] << 24;
  uint32_t delta = count - P.vs_count[pcb];
  int newer = !P.vs_count_valid[pcb] || (delta != 0 && delta < 0x80000000u);
  if (!newer && memcmp(destination, packet, CAR_LINK_PACKET) != 0)
    P.vs_received[pcb] = 0; /* changed data at an old count is not observable */
  memcpy(destination, packet, CAR_LINK_PACKET);
  if (newer) {
    P.vs_count[pcb] = count;
    P.vs_count_valid[pcb] = 1;
    P.vs_received[pcb] = link_now();
  }
}

/* clCarDispManager::setupOtherCar: a traffic car comes on the road; its model */
static int on_other_setup(uint32_t slot, uint32_t type) {
  int i = (int)slot - TRAFFIC_SLOT0;
  if (i >= 0 && i < CAR_TRAFFIC) P.traffic_model[i] = type - TRAFFIC_TYPE0 < 4 ? TRAFFIC_MODEL[type - TRAFFIC_TYPE0] : 0;
  return 1;
}

static void first_frame(car_state *c);

int car_start(car_state *c, int course, int manual, const car_spec *spec) {
  if (PG.requested && (PG.started || PG.observation.status != CAR_GHOST_PREPARED)) return -1;
  if (PG.arcade_on && car_course_city(course) != PG.arcade.city) {
    PG.observation.status = CAR_GHOST_FAILED; P.ready = 0; return -1;
  }
  if (!PG.requested) ghost_runtime_clear();
  uint64_t ta_recording_token = PT.pending;
  memset(&PT, 0, sizeof PT);
  if (c) car_clear_junction(&c->race);
  story_carry.loaded = 0;
  if (story_carry.valid && !story_carry.armed) car_story_carry_cancel();
  /* a fresh arcade memory image per race, like a fresh boot of CSeq::Init */
  P.ready = 0;
  P.se_backfire_on = 0;
  mileage_style_reset(&P.drive_style);
  memset(P.vs_received, 0, sizeof P.vs_received);
  memset(P.vs_count_valid, 0, sizeof P.vs_count_valid);
  P.vs_race = 0;
  if (course < 0 || course >= CAR_COURSES || rc_load_image(P.image) != 0) {
    car_story_carry_cancel();
    return -1;
  }
  P.course = course;
  P.manual = manual != 0;
  P.spec = spec ? *spec : CAR_SPEC_FD3S;
  P.top_lever = P.spec.gears - 1;
  memset(P.traffic_model, 0, sizeof P.traffic_model);
  rc_reset_heap();
  rc_on_hook = on_hook;
  rc_on_other_setup = on_other_setup;
  /* Time attack traffic is optional; other modes explicitly clear the flag. */
  uint32_t cfg = rc_alloc(0x200);
  W32(cfg + CFG_CAR, P.spec.type);
  W32(cfg + CFG_POWER, (uint32_t)P.spec.power);
  W32(cfg + CFG_HANDLING, (uint32_t)P.spec.handling);
  W32(cfg + CFG_TRANS, P.manual ? TRANS_MT : TRANS_AT);
  W32(cfg + CFG_STAGE, COURSES[course].stage);
  W32(cfg + CFG_AREA, COURSES[course].area);
  WF(cfg + CFG_DIST, COURSES[course].dist);
  WF(cfg + CFG_GOAL, COURSES[course].dist + MF(TA_LENGTHS + 8 * (COURSES[course].stage - TA_STAGE0) + 4));
#ifdef WMMT_EGL
  if (!PG.requested && getenv("WMMT_TA_GOAL")) /* test: the goal this many m from the start */
    WF(cfg + CFG_GOAL, COURSES[course].dist + 1000.0f * (float)atof(getenv("WMMT_TA_GOAL")));
#endif
  W32(cfg + CFG_MODE, MODE_TIME_ATTACK);
  W32(cfg + CFG_TA_TRAFFIC, (uint32_t)P.ta_traffic);
  if (P.has_rival) {
    W32(cfg + CFG_TA_TRAFFIC, 0u); /* the story mode's race against its rivals */
    W32(cfg + CFG_MODE, MODE_STORY);
    W32(cfg + CFG_LEVEL, (uint32_t)P.rival[0].level);
    W32(cfg + CFG_LOSSES, (uint32_t)P.rival[0].losses);
    /* the save is the card: with one, a car tuned 1 step or less meets the exhibition
     * characters' easy settings from series 36 on (CSeq::Init) */
    W8(cfg + CFG_CARD, 1u);
    W32(cfg + CFG_RIVALS, (uint32_t)P.n_rival);
    for (int i = 0; i < P.n_rival; ++i) {
      W32(cfg + CFG_RIVAL_CHAR + 4 * (uint32_t)i, (uint32_t)P.rival[i].character);
      W32(cfg + CFG_RIVAL_CAR + 4 * (uint32_t)i, P.rival[i].type);
    }
    W32(cfg + CFG_SERIES, (uint32_t)P.rival[0].series);
    /* the series' own start and goal, as the story's menus set them (GetConfigRaceField_Story:
     * the SConfigRaceField is the first 6 words of the series' config) */
    uint32_t field = rc_alloc(0x40);
    call(f_899b378, 4, field, STORY_CONFIG, 0u, (uint32_t)P.rival[0].series);
    for (int i = 0; i < 6; ++i) W32(cfg + RACE_FIELD + 4 * i, M32(field + 4 * i));
    fprintf(stderr, "story series %d (loop %d, lost %d): stage %u area %u dist %.0f goal %.0f\n", P.rival[0].series,
            P.rival[0].level, P.rival[0].losses, M32(cfg + CFG_STAGE),
            M32(cfg + CFG_AREA), MF(cfg + CFG_DIST), MF(cfg + CFG_GOAL));
  }
  rc_link_tx = rc_link_rx = 0;
  rc_on_link_receive = rc_on_link_send = NULL;
  if (P.vs_on) { /* a versus (clRaceThread::initJoin) */
    W32(cfg + CFG_MODE, MODE_BATTLE);
    W32(cfg + CFG_TA_TRAFFIC, 0u);
    uint32_t field = rc_alloc(0x40), eramp = M32(M32(JOIN_RAMPS + 4u * (uint32_t)P.vs_ramp) + 8);
    call(f_8992604, 2, field, eramp);
    for (int i = 0; i < 6; ++i) W32(cfg + RACE_FIELD + 4 * i, M32(field + 4 * i));
    WF(cfg + CFG_GOAL, MF(cfg + CFG_DIST) + P.vs_km * 1000000.0f);
    W8(cfg + CFG_LINK_NO_BAND, 0u);
    /* the places: PCB ids in order (initJoin's from the join list) */
    int place = 0;
    for (int i = 0; i < P.vs_n; ++i) place += P.vs[i].pcb < P.vs_pcb;
    W32(cfg + CFG_LINK_PLACE, (uint32_t)place);
    W32(cfg + CFG_LINK_OTHERS, (uint32_t)P.vs_n);
    for (int i = 0; i < P.vs_n; ++i) {
      int pl = P.vs[i].pcb > P.vs_pcb;
      for (int j = 0; j < P.vs_n; ++j) pl += P.vs[j].pcb < P.vs[i].pcb;
      W32(cfg + CFG_LINK_PCB + 4u * (uint32_t)i, (uint32_t)P.vs[i].pcb);
      W32(cfg + CFG_LINK_OTHER_PLACE + 4u * (uint32_t)i, (uint32_t)pl);
      W32(cfg + CFG_LINK_CAR + 4u * (uint32_t)i, P.vs[i].type);
      W32(cfg + CFG_LINK_POWER + 4u * (uint32_t)i, (uint32_t)P.vs[i].power);
      W32(cfg + CFG_LINK_HANDLING + 4u * (uint32_t)i, (uint32_t)P.vs[i].handling);
    }
    W32(cfg + CFG_LINK_RANDOM, P.vs_seed);
    rc_link_pcb = (uint32_t)P.vs_pcb;
    rc_link_tx = rc_alloc(LINK_BUF);
    rc_link_rx = rc_alloc(LINK_BUF * CAR_LINK_MACHINES);
    rc_on_link_receive = link_receive;
    rc_on_link_send = link_send;
    fprintf(stderr, "versus pcb %d place %d others %d ramp %d (ERamp %u): stage %u area %u dist %.0f goal %.0f\n", P.vs_pcb, place,
            P.vs_n, P.vs_ramp, eramp, M32(cfg + CFG_STAGE), M32(cfg + CFG_AREA), MF(cfg + CFG_DIST), MF(cfg + CFG_GOAL));
  }
  if (P.ten_stage) { /* the 10-in-a-row (clRaceThread::initTen): its level and course's start */
    W32(cfg + CFG_MODE, MODE_TEN_FIGHT);
    W32(cfg + CFG_TA_TRAFFIC, 0u);
    W32(cfg + CFG_TEN_LEVEL, (uint32_t)P.ten_level);
    uint32_t field = rc_alloc(0x40);
    call(f_89923e4, 3, field, (uint32_t)P.ten_stage, (uint32_t)P.ten_level);
    for (int i = 0; i < 6; ++i) W32(cfg + RACE_FIELD + 4 * i, M32(field + 4 * i));
    fprintf(stderr, "ten stage %d level %d: area %u dist %.0f goal %.0f\n", P.ten_stage, P.ten_level, M32(cfg + CFG_AREA),
            MF(cfg + CFG_DIST), MF(cfg + CFG_GOAL));
  }
  if (PG.requested) {
    if (P.has_rival || P.vs_on || P.ten_stage) { PG.observation.status = CAR_GHOST_FAILED; return -1; }
    for (int i = 0; i < 6; ++i) W32(cfg + RACE_FIELD + 4u * (uint32_t)i, PG.config.race_field[i]);
    W32(cfg + CFG_MODE, PG.config.kind == CAR_GHOST_QUALIFICATION ? MODE_TIME_ATTACK : 8u);
    W32(cfg + CFG_TA_TRAFFIC, 0);
    W8(cfg + CFG_CARD, 1);
    int ready;
    if (PG.config.kind == CAR_GHOST_DEFAULT) {
      W32(cfg + 0xbcu, PG.config.rival.type);
      for (int i = 0; i < 3; ++i) W32(cfg + 0xc0u + 4u * (uint32_t)i, (uint32_t)PG.config.trail_band[i]);
      W32(cfg + 0xccu, 0u); /* intentional original default-AI, not missing-trail fallback */
      W8(cfg + 0xd0u, PG.config.native_flags[0]); W8(cfg + 0xd1u, PG.config.native_flags[1]);
      ready=ghost_default.active && !ghost_runtime_active();
      if (ready && PG.config.record_player) {
        ghost_format_policy policy;
        int recording = car_ghost_arcade_policy(&PG.arcade,&policy) && ghost_runtime_begin_qualification(&policy);
        if (!recording && !PG.record_required) PG.config.record_player = 0;
        else ready = recording;
      }
    } else if (PG.config.kind == CAR_GHOST_CHALLENGE) {
      W32(cfg + 0xbcu, PG.config.rival.type);
      for (int i = 0; i < 3; ++i) W32(cfg + 0xc0u + 4u * (uint32_t)i, (uint32_t)PG.config.trail_band[i]);
      uint32_t name = rc_alloc(sizeof GHOST_INPUT_TOKEN);
      memcpy(VA(name), GHOST_INPUT_TOKEN, sizeof GHOST_INPUT_TOKEN);
      W32(cfg + 0xccu, name);
      W8(cfg + 0xd0u, PG.config.native_flags[0]); W8(cfg + 0xd1u, PG.config.native_flags[1]);
      ready = ghost_runtime_begin(PG.config.record_player);
      if (!ready && PG.config.record_player && !PG.record_required) {
        PG.config.record_player = 0;
        ready = ghost_runtime_begin(0);
      }
    } else {
      ghost_format_policy policy = {.stage=PG.config.race_field[0], .area_allowed=ghost_area_allowed};
      ready = ghost_runtime_begin_qualification(&policy);
    }
    if (!ready) { PG.observation.status = CAR_GHOST_FAILED; return -1; }
    if (PG.config.record_player) {
      /* Original CSeq owns the COMPLETE sampler construction/config/start
       * sequence. The private variant gates its mode-6 recording branch only
       * for this explicit qualification session; no host-made sampler. */
      ghost_configure_recording(cfg);
    }
  } else if (ta_recording_token && M32(cfg + CFG_MODE) == MODE_TIME_ATTACK) {
    ghost_begin_ta_recording(cfg, ta_recording_token);
  }
  if (story_carry.valid && story_carry.armed) {
    story_carry.target_stage = M32(cfg + CFG_STAGE);
    story_carry.initializing = 1;
    if (!carry_target_matches()) car_story_carry_cancel();
  }
  call(f_89878c4, 1, cfg);
  if (PG.arcade_on && PG.arcade.raw_ramp >= CAR_GHOST_TA_RAMP_BASE) {
    /* Original mode 8 has 300 seconds and no TA checkpoint extensions.
     * Allow the field's entire recording window plus a minute for traffic. */
    uint32_t ticks = PG.config.race_field[0] == GHOST_LONG_TA_STAGE ?
      GHOST_LONG_TA_MAX_TICKS : GHOST_MAX_TICKS;
    WF(RACE_TIME_LEFT, (float)ticks / 60.0f + 60.0f);
  }
  story_carry.initializing = 0;
  P.vs_race = P.vs_on ? P.vs_n : 0;
  P.vs_on = 0; /* car_set_versus is for this race only */
  call(f_89a2584, 1, fbits(1.0f / 60.0f));
  call(f_89a2548, 1, fbits(1.0f));
  /* the time attack starts rolling (GetSeqStartOfs_Mc): CState's countdown (Prep_CountDown,
   * 4 s) has the pilot drive, then the race runs with the car in the player's hands */
  P.m = M32(MACHINE_PTR);
  P.gen = M32(OTHER_GEN_PTR);
  P.gin = rc_alloc(0x40);
  P.gin_ptr = rc_alloc(4);
  W32(P.gin_ptr, P.gin);
  P.disp = rc_alloc(0x260);
  P.eff = rc_alloc(0x100);
  P.cam = rc_alloc(0x100);
  P.mirror = rc_alloc(0x100);
  P.jct = rc_alloc(8);
  P.jct_select = rc_alloc(16);
  P.jct_decide_line = rc_alloc(36);
  P.info_race = rc_alloc(0x40);
  P.info_map = rc_alloc(0x20);
  P.info_sign = rc_alloc(8);
  P.lines = rc_alloc(48);
  P.ten_line = rc_alloc(24);
  P.title_log = rc_alloc(CAR_TITLE_LOG);
  P.info_story = rc_alloc(0x40);
  P.info_ten = rc_alloc(0xa0);
  P.result = rc_alloc(0x40);
  P.first_pt = rc_alloc(0x20);
  if (PG.requested) {
    PG.started = 1;
    PG.info = rc_alloc(8);
    PG.observation.status = CAR_GHOST_RUNNING;
    if (PG.config.kind == CAR_GHOST_CHALLENGE && !ghost_target_valid()) {
      PG.observation.status = CAR_GHOST_FAILED; ghost_runtime_stop(); return -1;
    }
    PG.observation.native_target_valid = PG.config.kind == CAR_GHOST_CHALLENGE;
    if (PG.config.record_player) {
      PG.recorder = M32(GHOST_SAMPLER_PTR);
      int ta_field = PG.arcade_on && PG.arcade.raw_ramp >= CAR_GHOST_TA_RAMP_BASE;
      if (!(ta_field ? ghost_extend_ta_recorder : ghost_recorder_valid)(PG.recorder, PG.config.race_field[0])) {
        if (PG.record_required) {
          PG.observation.status = CAR_GHOST_FAILED; ghost_runtime_stop(); return -1;
        }
        PG.recorder = 0;
        PG.config.record_player = 0;
        ghost_runtime_discard_recording();
        W32(GHOST_SAMPLER_PTR, 0u);
        if (PG.config.kind == CAR_GHOST_DEFAULT) ghost_runtime_stop();
      }
    }
    PG.observation.native_default_ai_valid = PG.config.kind == CAR_GHOST_DEFAULT && ghost_default_ai_valid();
    if (PG.config.kind == CAR_GHOST_DEFAULT && !PG.observation.native_default_ai_valid) { PG.observation.status = CAR_GHOST_FAILED; return -1; }
  } else if (PT.token) {
    PT.recorder = M32(GHOST_SAMPLER_PTR);
    if (!ghost_extend_ta_recorder(PT.recorder, PT.field[0])) {
      memset(&PT, 0, sizeof PT);
      ghost_runtime_stop();
    }
  }
  P.ready = 1;
  first_frame(c);
  ghost_observe();
  if (PG.requested && PG.observation.status == CAR_GHOST_FAILED) { P.ready = 0; return -1; }
  return 0;
}

/* clCarDisp::update: tyre nodes +0x8c..+0x98 (FL, FR, RL, RR) take SInfoCarDisp +0x188, +0x148,
 * +0x208, +0x1c8; their spin nodes +0x9c..+0xa8 a turn about x by +0x248..+0x254 */
static void read_tyres(float tyre[4][16], float rot[4]) {
  static const uint32_t at[4] = { 0x188, 0x148, 0x208, 0x1c8 };
  for (int k = 0; k < 4; ++k) {
    memcpy(tyre[k], VA(P.disp + at[k]), sizeof tyre[k]);
    rot[k] = MF(P.disp + 0x248 + 4 * (uint32_t)k);
  }
}

static void read_effect(car_effect *e) {
  e->spark = MF(P.eff + 0x68);
  memcpy(e->at, VA(P.eff + 0x6c), sizeof e->at);
  memcpy(e->dir, VA(P.eff + 0x78), sizeof e->dir);
  e->backfire_pulse = (unsigned char)M8(P.eff + 0x84);
  memcpy(e->backfire_vec, VA(P.eff + 0x30), sizeof e->backfire_vec);
  double x = e->backfire_vec[0], y = e->backfire_vec[1], z = e->backfire_vec[2];
  double length = sqrt(x*x + y*y + z*z);
  e->backfire_type = isfinite(length) && length < (double)INT_MAX + 1.0
                       ? (int)length % 2 : -1;
}

static void read_body(car_state *c) {
  call(f_89b45d0, 2, P.m, P.disp);
  /* igMatrix44f is row-major with the translation in the last row: the same
   * memory layout as a GL column-major matrix. Units are already display units. */
  memcpy(c->body, VA(P.disp + 4), sizeof c->body);
  read_tyres(c->tyre, c->tyre_rot);
#ifdef __ANDROID__
  /* clCarEffectManager::update (0x85fa7d1): its four trail matrices are
   * the world-space SInfoCarDisp +0x44..+0x104, not the display-wheel
   * matrices read by read_tyres. Preserve the original index pairing. */
  for (int k = 0; k < 4; ++k)
    memcpy(c->track_matrix[k], VA(P.disp + 0x44 + 0x40u * (uint32_t)k), sizeof c->track_matrix[k]);
#endif
  c->brake = M8(P.disp + 0x144);
  c->spot = M8(P.disp + 0x146) == 1;
  call(f_89b410c, 2, P.m, P.eff);
  read_effect(&c->effect);
  /* Read the already-produced native effect; no extra engine call or RNG draw.
   * clCarEffectManager type0 uses +18/+24, +30, +50/+54 (not tyre-track alpha). */
  if (c->tire_smoke_tick == UINT64_MAX) {
    memset(&c->tire_smoke,0,sizeof c->tire_smoke);
    c->tire_smoke_valid=0;
  } else {
    ++c->tire_smoke_tick;
    c->tire_smoke_valid=tire_smoke_input_from_effect(&c->tire_smoke,VA(P.eff),TIRE_SMOKE_EFFECT_BYTES);
  }
#ifdef __ANDROID__
  for (int k = 0; k < 4; ++k) c->track_alpha[k] = MF(P.eff + 0x40 + 4u * (uint32_t)k);
#endif
  const float *M = c->body;
  c->pos[0] = M[12];
  c->pos[1] = M[13];
  c->pos[2] = M[14];
  c->yaw = atan2f(M[8], M[10]);
  c->pitch = asinf(fmaxf(-1.0f, fminf(1.0f, M[9])));
  c->roll = atan2f(M[1], M[5]);
}

/* SInfoCarCamera: igMatrix44f view (world -> camera; row-major with the translation
 * last, so GL column-major as it stands), horizontal fov at +0x40, near plane at +0x44,
 * the radial blur at +0x48 (clRaceThread::yield hands it to clGraphicFrame::setBlur).
 * clRaceThread::race takes CSeq::GetInfoCarCamera's: CMachine's with the play view and true
 * (the camera sways with the car, CCamSway, so once per arcade frame), but in the
 * 10-in-a-row while a rival comes on (play state 1) CSeqCamTen's, which shows it arriving,
 * and once a story or 10-in-a-row race reaches its goal (state 8) CSeqCamGoal's. */
static void read_camera(car_state *c) {
  W32(PLAY_VIEW, (uint32_t)P.view);
  call(f_8982338, 1, P.cam);
  memcpy(c->cam_view, VA(P.cam), sizeof c->cam_view);
  const float *V = c->cam_view;
  for (int j = 0; j < 3; j++) c->cam_pos[j] = -(V[12] * V[4 * j] + V[13] * V[4 * j + 1] + V[14] * V[4 * j + 2]);
  c->cam_fov = MF(P.cam + 0x40);
  c->cam_near = MF(P.cam + 0x44);
  c->cam_blur = fminf(1.0f, fmaxf(0.0f, MF(P.cam + 0x48)));
  /* the back mirror's (clRaceThread::yield: CSeq::GetInfoMirrorCamera, CMachine's
   * GetInfoCarMirror: no sway), only for the view from the roof, the one that shows it */
  c->mirror = P.view == CAR_VIEW_ROOF && P.mirror && (call(f_8982580, 1, P.mirror) & 0xff);
  if (c->mirror) {
    memcpy(c->mirror_view, VA(P.mirror), sizeof c->mirror_view);
    c->mirror_fov = MF(P.mirror + 0x40);
    c->mirror_near = MF(P.mirror + 0x44);
  }
}

void car_view(int view) { P.view = view; }

/* SInfoJctBlockDisp, as CSeq::GetInfoJctBlockDisp gets it for clCourseArrow: the two
 * junction blocks (arrow boards closing the branches off the course) to show now. */
static void read_jct_blocks(car_state *c) {
  call(f_89c4000, 3, P.jct, M32(P.m + M_AREA_PROC), P.m + M_AREA_PROC + 4);
  for (int i = 0; i < 2; i++) c->jct_block[i] = (int)M32(P.jct + 4 * i);
}

/* Clear snapshots on teardown; does not mutate the engine's branch choice. */
void car_clear_junction(car_race *r) {
  if (!r) return;
  r->jct_select_valid = r->jct_state = r->jct_left_area = r->jct_right_area = 0;
  r->jct_distance = 0;
  r->jct_line_valid = 0;
  memset(r->jct_line, 0, sizeof r->jct_line);
}

/* VA checks the start only; check the whole span before touching scratch or
 * the top-level engine pointers. Nested virtual-call objects remain engine-owned. */
static int jct_span(uint32_t p, uint32_t n) {
  return rc_mem && p >= RC_MEM_BASE && n <= RC_MEM_SIZE && p - RC_MEM_BASE <= RC_MEM_SIZE - n;
}
static void read_junction(car_race *r) {
  car_clear_junction(r);
  if (!P.ready || !jct_span(P.jct_select, 16) || !jct_span(P.jct_decide_line, 36)) return;
  uint32_t machine = M32(MACHINE_PTR), jct = M32(0x98028f0u);
  if (!jct_span(machine, 0x974) || (jct && !jct_span(jct, 12))) return;
  if (jct) {
    uint32_t table = M32(jct), proc = M32(machine + 0x938u);
    if (!jct_span(table, 0x14) || !jct_span(proc, 4)) return;
    uint32_t proc_table = M32(proc);
    if (!jct_span(proc_table, 0x28)) return;
  }
  memset(VA(P.jct_select), 0, 16);
  memset(VA(P.jct_decide_line), 0, 36);
  if (call(f_8982f4c, 1, P.jct_select) & 0xffu) {
    uint32_t state = M32(P.jct_select), left = M32(P.jct_select + 4), right = M32(P.jct_select + 8);
    float distance = MF(P.jct_select + 12);
    if (state <= 3 && isfinite(distance) && (state == 0 || (left < 75 && right < 75))) {
      r->jct_select_valid = 1; r->jct_state = (int)state;
      r->jct_left_area = (int)left; r->jct_right_area = (int)right;
      r->jct_distance = distance;
    }
  }
  if (call(f_8983cd8, 3, P.jct_decide_line, P.jct_decide_line + 12, P.jct_decide_line + 24) & 0xffu) {
    float v[3][3]; memcpy(v, VA(P.jct_decide_line), sizeof v);
    int valid = 1;
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) valid &= isfinite(v[i][j]);
    if (valid) { memcpy(r->jct_line, v, sizeof v); r->jct_line_valid = 1; }
  }
}

/* The time attack's consoles: S2DInfoRace (+4 time left, +8 time since the start, +0xc mm
 * to the goal) and S2DInfoMap (+0 area, +4 the next, +8 z, +0xc x in display units, +0x10
 * heading), as CSeq hands them to clStandardConsole and clMiniMap; the sections from the
 * CTimeKeeper the way clWorkSpace gets them for the section times. */
/* Get2DInfoRace uses FLT_MAX as the unavailable sentinel. Check before fmaxf
 * converts a negative or NaN distance to zero for the existing displays. */
static int race_remain_valid(float mm) { return isfinite(mm) && mm >= 0.0f && mm < FLT_MAX; }

static void read_race(car_race *r) {
  read_junction(r);
  call(f_8983950, 1, P.info_race);
  call(f_8983874, 1, P.info_map);
  call(f_898380c, 1, P.info_sign);
  { /* CSeq::Exec 0x8984ff7: do not use elapsed time or the absolute odometer. */
    uint32_t m = M32(MACHINE_PTR);
    r->story_distance_valid = m != 0 && !P.ten_stage;
    r->story_distance = r->story_distance_valid ? (MF(m + 0x970u) - MF(0x9802908u)) * 0.001f : 0.0f;
  }
  r->countdown = MF(P.info_race);
  r->time_left = MF(P.info_race + 4);
  float remain_mm = MF(P.info_race + 0xc);
  r->remain_valid = race_remain_valid(remain_mm);
  r->remain = fmaxf(0.0f, remain_mm * 0.001f);
  uint32_t st = M32(STATE);
  int was = r->state;
  r->play_state = (int)st;
  r->state = st >= 7 && st <= 8 ? CAR_RACE_GOAL : st >= 4 && st <= 6 ? CAR_RACE_TIME_UP : CAR_RACE_RUN;
  /* clRaceThread::race returns on clWorkSpace::getPlayState 8 (setGoal) or 6 (setTimeUp);
   * in the time attack GoalWait (7) gives way to Goal the next frame (Ck_GoalWait_2_Goal).
   * A story race also ends on 3 (Defeat) and 10 (Suspend: Ck_X_2_Suspend, the odometer past
   * the episode's distance at 0x9802a7c; clRaceThread::race fades out and returns). */
  r->over = st == 8 || st == 6 || st == 3 || st == 10;
  /* clWorkSpace::updateRace (0x88bd583) copies the SPlayResult and
   * getOdoCount (0x88bd100) reads its +0xc. Freeze the first valid result
   * so later pilot movement and rejected link ticks cannot change mileage. */
  if (r->over && st != 10 && !r->mileage_valid && (call(f_898317c, 1, P.result) & 255u)) {
    float mm = MF(P.result + 0xcu);
    if (race_remain_valid(mm)) r->mileage_mm = mm, r->mileage_valid = 1;
  }
  /* the arcade's total runs on after the time is up; the console's stops there */
  if (r->state != CAR_RACE_TIME_UP || was != CAR_RACE_TIME_UP) r->total = MF(P.info_race + 8);
  uint32_t tk = M32(TIME_KEEPER_PTR);
  int n = tk ? (int)M32(tk + TK_COUNT) : 0, next = tk ? (int)M32(tk + TK_NEXT) : 0;
  int section = next - 1;
  if (n > 1 && section > r->section && section < n - 1) /* a checkpoint passed (not the goal) */
    r->extended = MF(M32(tk + TK_EXTEND) + 4 * (uint32_t)(next - 1));
  r->sections = n - 1 < CAR_SECTIONS ? n - 1 : CAR_SECTIONS;
  r->section = section < 0 ? 0 : section;
  for (int k = 0; k < next && k <= CAR_SECTIONS; k++) r->split[k] = MF(M32(tk + TK_SPLIT) + 4 * (uint32_t)k);
  r->area = (int)M32(P.info_map);
  { /* CSeq::GetInfoMyCarPlace */
    uint32_t m = M32(MACHINE_PTR);
    r->place = m ? (int)M32(M32(m + 0x93cu)) : 0;
    r->place_at = m ? MF(m + 0x7b4u + 0x1bcu) - MF(m + 0x7b4u + 0x180u) : 0.0f;
  }
  r->next_area = (int)M32(P.info_map + 4);
  r->map_z = MF(P.info_map + 8);
  r->map_x = MF(P.info_map + 0xc);
  r->map_angle = MF(P.info_map + 0x10);
  r->sign = (int)M32(P.info_sign + 4);
  { /* GetMapText(EAreaId, float) 0x899f4d0 (a stub in the recompile): table 0x9778980 of
     * {area, text below, threshold, text at or above}, keyed by the CSlit's 0x1bc - 0x180 */
    uint32_t slit = M32(0x98028e4u) + 0x7b4u, row = 0x9778980u + 16u * (uint32_t)r->area;
    float at = MF(slit + 0x1bc) - MF(slit + 0x180);
    r->map_text = r->area >= 0 && r->area < 75 ? (int)M32(MF(row + 8) > at ? row + 4 : row + 0xc) : 0;
  }
  /* clGoalLine::clLine::update: the goal's row while the race info has the goal ahead, the
   * checkpoint's whenever CSeq gives one */
  r->lines = 0;
  if (MF(P.info_race + 0xc) > 0.0f && (call(f_898f518, 2, P.lines, P.lines + 12) & 0xffu)) r->lines |= 1;
  if (call(f_898f6d4, 2, P.lines + 24, P.lines + 36) & 0xffu) r->lines |= 2;
  memcpy(r->line, VA(P.lines), sizeof r->line);
  if (P.ten_stage) {
    /* S2DInfoTenFight: +0 rivals beaten, +4.. the s each took, +0x84 s on the one now, +0x88
     * the rolling start's gear, +0x8c mm behind it (float), +0x90/+0x91 SwName, SwGear */
    memset(VA(P.info_ten), 0, 0xa0);
    call(f_8982be8, 1, P.info_ten);
    r->ten_beaten = (int)M32(P.info_ten);
    r->ten_rival = (int)M32(TEN_RIVAL_NO);
    for (int k = 0; k < 32; ++k) r->ten_time[k] = MF(P.info_ten + 4 + 4 * (uint32_t)k);
    r->ten_now = MF(P.info_ten + 0x84);
    r->ten_gear = (int)M32(P.info_ten + 0x88);
    r->ten_gap = MF(P.info_ten + 0x8c) * 0.001f;
    r->ten_sw_name = M8(P.info_ten + 0x90);
    r->ten_sw_gear = M8(P.info_ten + 0x91);
    uint32_t ci = M8(CUTIN_ON) ? M32(CUTIN_INFO) : 0;
    r->cut_char = ci ? (int)M32(ci + 0x4c) : -1;
    r->cut_start = ci && M8(ci + 0x50);
    r->cut_lose = ci && M8(ci + 0x51);
    r->ten_line_on = (call(f_8983e5c, 2, P.ten_line, P.ten_line + 12) & 0xffu) && st == 2;
    r->ten_gap_valid = r->ten_line_on && r->ten_rival >= 0 && r->ten_rival < P.n_ten && isfinite(r->ten_gap);
    memcpy(r->ten_line, VA(P.ten_line), sizeof r->ten_line);
    /* all ten beaten (Goal): SPlayResult +0x14, CState::GetTenFightResult -> CTenSeq::GetResult
     * of the time left: 3 gold, 2 silver, 1 bronze (the workspace's TenResult, the card's) */
    if (st == 8 && !r->ten_medal) {
      call(f_898317c, 1, P.result);
      r->ten_medal = (int)M32(P.result + 0x14);
    }
  }
  if (P.vs_race) {
    /* yt::CSeq::Get2DInfoBattle (clJoinConsole's getInfoJoinRank / getInfoJoinAdvantage): the
     * player's odometer (CMachine +0x970) less each link rival's (CLxRival: +8 on the road,
     * +0x240 its packet, +0x30 there the odometer; 0 while it is not on), mm; the rank counts
     * those ahead */
    uint32_t m = M32(MACHINE_PTR);
    float odo = m ? MF(m + 0x970u) : 0.0f;
    r->vs_rank = 0;
    double now = link_now();
    for (int i = 0; i < CAR_RIVALS; ++i) {
      uint32_t lx = M32(LX_RIVALS + 4u * (uint32_t)i);
      r->vs_on[i] = lx && i < P.vs_race;
      r->vs_fresh[i] = 0;
      if (!r->vs_on[i]) continue;
      uint32_t packet = M32(lx + 0x240u);
      int pcb = P.vs[i].pcb;
      r->vs_pcb[i] = pcb;
      r->vs_observed[i] = pcb >= 0 && pcb < CAR_LINK_MACHINES ? P.vs_received[pcb] : 0;
      int on_road = M8(lx + 8u) != 0;
      float d = odo - (on_road && packet ? MF(packet + 0x30u) : 0.0f);
      r->vs_gap[i] = d * 0.001f;
      r->vs_fresh[i] = m && on_road && packet && pcb >= 0 && pcb < CAR_LINK_MACHINES &&
          isfinite(odo) && isfinite(d) && car_link_time_fresh(now, P.vs_received[pcb]);
      if (d < 0.0f) r->vs_rank++;
    }
  }
  if (P.vs_race && (st == 3 || st == 6 || st == 8) && !r->vs_place) {
    /* a versus: SPlayResult +0 the place by the odometers (CState::Prep_Goal's ranking, 0 first;
     * the link's machines' from their finish packets), +0x10 whether the goal was reached */
    call(f_898317c, 1, P.result);
    r->vs_place = (int)M32(P.result) + 1;
    r->won = M32(P.result) == 0;
  }
  if ((st == 3 || st == 6 || st == 8 || st == 10) && !r->title_log_on) {
    /* the run's log for the titles (yt::CTitle's, CSeq::GetPlayLog) once it is over: the
     * _TitleRunningLog_ judgeTitle hands youTitle::GetTitleList at _TitleData_ +0x384 */
    memset(VA(P.title_log), 0, CAR_TITLE_LOG);
    call(f_898332c, 1, P.title_log);
    memcpy(r->title_log, VA(P.title_log), CAR_TITLE_LOG);
    r->title_log_on = 1;
  }
  /* Get2DInfoStory can leave individual output slots unwritten. Mark them
   * before each call so an old gap cannot masquerade as a current leader. */
  memset(r->story_gap_valid, 0, sizeof r->story_gap_valid);
  if (P.has_rival) {
    /* S2DInfoStory +0: mm (a float) the rival is behind (negative: ahead). At the end (states 3
     * Defeat, 6 TimeUp, 8 Goal) SPlayResult has the player's place by the odometers
     * (CState::Prep_Goal's ranking, 0 first) at +0 and whether the goal was reached at +0x10. */
    for (int i = 0; i < 3; ++i) WF(P.info_story + 4 * i, NAN);
    call(f_898287c, 1, P.info_story);
    /* +4*i is gap; +0xc+i is the independent picture-enable flag. Keep the
     * previous display gap when unwritten, but do not mark it valid for rank. */
    for (int i = 0; i < 3; ++i) {
      float mm = MF(P.info_story + 4 * i);
      r->story_gap_valid[i] = isfinite(mm);
      if (r->story_gap_valid[i]) r->story_gap[i] = mm * 0.001f;
      r->story_on[i] = M8(P.info_story + 0xc + i);
    }
    r->gap = r->story_gap[0];
    /* clRaceThread::finiStory: won = rank 0 && !TimeUp && !Retire. GetPlayResult only fills
     * the result for 3/6/8 (mask 0x148); on 10 (Suspend: the episode's distance run without a
     * Defeat) the workspace keeps initRace's rank 0, so surviving the distance is a win. */
    if (st == 10) r->won = 1;
    else if (st == 3 || st == 6) r->won = 0;
    else if (st == 8) {
      call(f_898317c, 1, P.result);
      r->won = M32(P.result) == 0;
    }
  }
}

int car_title_list(const unsigned char *data, int n, int out[3]) {
  /* the image holds youTitle's tables; it is in once any race has been */
  if (!rc_mem && rc_load_image(P.image) != 0) return 0;
  /* above the stack call() starts at: _TitleData_ there, then the 3 slots */
  uint32_t td = RC_STACK_TOP - 0x800, list = RC_STACK_TOP - 0x40;
  memset(VA(td), 0, 0x7c0);
  memcpy(VA(td), data, (size_t)(n < 0x7c0 ? n : 0x7c0));
  call(f_858d8e8, 2, td, list);
  int got = 0;
  for (int i = 0; i < 3; ++i) {
    out[i] = (int)M32(list + 4 * (uint32_t)i);
    got += out[i] != 0;
  }
  return got;
}

const char *car_jct_block_name(int id) {
  if (id <= 0 || id >= CAR_JCT_BLOCKS) return NULL;
  const char *name = (const char *)VA(M32(JCT_BLOCK_NAMES + 4 * (uint32_t)id));
  /* a few carry the scene file's prefix ("yazirushi_all:..."); no strchr in the patched SDK */
  for (const char *p = name; *p; ++p)
    if (*p == ':') return p + 1;
  return name;
}

/* What the traffic shows this frame: each car COtherGen has on the road and, in a versus, the
 * other machines' share (CLxOtherGen: they drive it, it comes in their packets, this machine
 * hits it), as CSeq::GetInfoOtherCarDisp asks one then the other. */
static void read_traffic(car_state *c) {
  c->n_traffic = 0;
  for (int i = 0; P.gen && i < CAR_TRAFFIC; i++) {
    if (!(call(f_89825a8, 3, (uint32_t)(TRAFFIC_SLOT0 + i), P.disp, 0u) & 0xff)) continue;
    car_traffic *t = &c->traffic[c->n_traffic++];
    t->model = P.traffic_model[i];
    memcpy(t->body, VA(P.disp + 4), sizeof t->body);
  }
}

/* The rivals (CSeq::GetInfoRivalCarDisp, rivals 1..): off the road (out of reach) it says so. */
static void read_rival(car_state *c) {
  for (int i = 0; i < CAR_RIVALS; ++i) {
    int ghost = i == 0 && PG.started && ((PG.config.kind == CAR_GHOST_CHALLENGE && ghost_target_valid()) || (PG.config.kind == CAR_GHOST_DEFAULT && ghost_default_ai_valid()));
    c->rival_shown[i] = (ghost || i < P.n_rival || i < P.vs_race || (P.ten_stage && i == 0)) && (call(f_8983488, 3, (uint32_t)i + 1u, P.disp, P.eff) & 0xff);
    c->rival_effect[i].spark = 0;
    c->rival_effect[i].backfire_pulse = 0;
    memset(c->rival_effect[i].backfire_vec, 0, sizeof c->rival_effect[i].backfire_vec);
    c->rival_effect[i].backfire_type = -1;
    if (c->rival_shown[i]) {
      read_effect(&c->rival_effect[i]);
      memcpy(c->rival_body[i], VA(P.disp + 4), sizeof c->rival_body[i]);
      read_tyres(c->rival_tyre[i], c->rival_tyre_rot[i]);
      c->rival_brake[i] = M8(P.disp + 0x144);
      c->rival_spot[i] = M8(P.disp + 0x146) == 1;
      if (ghost) {
        int finite = 1;
        for (int k = 0; k < 16; ++k) if (!isfinite(c->rival_body[i][k])) finite = 0;
        for (int wheel = 0; wheel < 4; ++wheel)
          for (int k = 0; k < 16; ++k) if (!isfinite(c->rival_tyre[i][wheel][k])) finite = 0;
        PG.observation.display_valid = finite;
        if (!finite) { c->rival_shown[i] = 0; PG.observation.status = CAR_GHOST_FAILED; }
      }
    }
  }
}

/* The realtime movies: clRaceThread::initStory makes a clMovieSystem (0x1c1fc bytes) and Inits
 * it with the movie, the player's car and the rivals'; its CMovieEditWraps runs CSeq in its
 * movie mode, each car a yt::CGhost driven along its recorded trail (data/rtmovie/trail). Each
 * frame clRaceThread::race runs CSeq::Exec, then UpDate(frame), GetRTMovieCamera and
 * GetRTMovieCarDisp for cars 0..3; the frame goes on by 1 up to the length Init gave. */
#define MOVIE_SYSTEM_SIZE 0x1c1fcu
static uint32_t movie;

float car_movie_start(car_state *c, int id, const car_spec *player, const car_rival *rivals, int n) {
  if (PG.requested || PT.token || PT.pending) car_ghost_clear(); /* movies cannot inherit a recorder */
  P.ready = 0;
  story_carry.loaded = 0; /* a pre-movie Init is not the final race */
  movie = 0;
  if (rc_load_image(P.image) != 0) {
    car_story_carry_cancel();
    return 0;
  }
  rc_reset_heap();
  P.spec = player ? *player : CAR_SPEC_FD3S;
  car_set_rivals(rivals, n);
  rc_on_hook = on_hook;
  rc_on_other_setup = on_other_setup;
  P.ten_stage = 0;
  uint32_t rival_type[CAR_RIVALS] = { 0 };
  for (int i = 0; i < P.n_rival; ++i) rival_type[i] = P.rival[i].type;
  uint32_t ms = rc_alloc(MOVIE_SYSTEM_SIZE);
  call(f_89fe784, 2, ms, 1u);
  call(f_89fd9d0, 6, ms, (uint32_t)id, P.spec.type, rival_type[0], rival_type[1], rival_type[2]);
  float len = (float)ST(0);
  fpop();
  call(f_89a2584, 1, fbits(1.0f / 60.0f));
  call(f_89a2548, 1, fbits(1.0f));
  P.m = M32(MACHINE_PTR);
  P.gen = M32(OTHER_GEN_PTR);
  P.gin = rc_alloc(0x40);
  P.gin_ptr = rc_alloc(4);
  W32(P.gin_ptr, P.gin);
  W32(P.gin + 0x14, 0xffffffffu);
  P.disp = rc_alloc(0x260);
  P.cam = rc_alloc(0x100);
  P.mirror = 0;
  movie = ms;
  memset(c, 0, sizeof *c);
  return len;
}

int car_movie_update(car_state *c, float frame) {
  if (!movie) return 0;
  call(f_8983f64, 1, P.gin_ptr);
  call(f_89fe890, 2, movie, fbits(frame));
  if (call(f_89fde9c, 2, movie, P.cam) & 0xff) {
    memcpy(c->cam_view, VA(P.cam), sizeof c->cam_view);
    const float *V = c->cam_view;
    for (int j = 0; j < 3; j++) c->cam_pos[j] = -(V[12] * V[4 * j] + V[13] * V[4 * j + 1] + V[14] * V[4 * j + 2]);
    c->cam_fov = MF(P.cam + 0x40);
    c->cam_near = MF(P.cam + 0x44);
    c->cam_blur = 0;
  }
  int shown = 0;
  for (int i = 0; i <= CAR_RIVALS; ++i) {
    int on = call(f_89fdfe8, 3, movie, (uint32_t)i, P.disp) & 0xff;
    shown |= on << i;
    if (!i) {
      if (!on) continue;
      memcpy(c->body, VA(P.disp + 4), sizeof c->body);
      read_tyres(c->tyre, c->tyre_rot);
      c->brake = M8(P.disp + 0x144);
      c->spot = M8(P.disp + 0x146) == 1;
      for (int j = 0; j < 3; j++) c->pos[j] = c->body[12 + j];
      continue;
    }
    c->rival_shown[i - 1] = on;
    if (on) {
      memcpy(c->rival_body[i - 1], VA(P.disp + 4), sizeof c->rival_body[i - 1]);
      read_tyres(c->rival_tyre[i - 1], c->rival_tyre_rot[i - 1]);
      c->rival_brake[i - 1] = M8(P.disp + 0x144);
      c->rival_spot[i - 1] = M8(P.disp + 0x146) == 1;
    }
  }
  c->n_traffic = 0;
  return shown;
}

void car_movie_end(void) { movie = 0; }

/* The top bar's reset key (a port extra: the arcade has no such key): the car put back on the
 * road where it is, facing the course in the start's lane, the way CSeq::Exec's 10-in-a-row
 * warp places it (0x898644c: yt::CSlit::GetFirstPoint at an odometer reading and a lateral
 * offset, CSeq::StartOfsAry[1] the start's; yt::CMachine::SetFirstPos, which sets the body,
 * the tyres, the gear for the speed, the hit and the camera effects, its speed the warp's
 * 120 km/h at most here, the car's own forward speed below that). */
#define START_OFS 0x9802920u     /* yt::CSeq::StartOfsAry: [1] the start's lateral offset */
#define WARP_SPEED 33333.333f    /* SetFirstPos's speed for the warp (mm/s: 120 km/h) */
static int hits; /* car_hits */
#define SPARK_CLEAR 30 /* frames without the scrape before its next start is a hit */
void car_hits(int on) { hits = on != 0; }

void car_reset(car_state *c) {
  if (PG.started) {
    PG.observation.status = CAR_GHOST_FAILED; /* a reset cannot produce a ranked Ghost recording */
    ghost_runtime_stop(); P.ready = 0; return;
  }
  if (PT.token) {
    memset(&PT, 0, sizeof PT);
    ghost_runtime_stop();
  }
  if (!P.ready) return;
  c->se.rev_enabled = 0;
  c->se.rev_sequence = 0;
  c->se.rev_vol = 0;
  c->engine_se = (car_engine_se){0};
  c->tire_smoke_tick=0;
  c->tire_smoke_valid=0;
  memset(&c->tire_smoke,0,sizeof c->tire_smoke);
  c->vel_ok = 0; /* (the warp is no hit) */
  uint32_t slit = P.m + 0x7b4u;
  float odo = MF(slit + 0x1bc), speed = fminf(fmaxf(c->speed * 1000.0f, 0.0f), WARP_SPEED);
  call(f_89c50c0, 4, P.first_pt, slit, fbits(odo), M32(START_OFS + 4));
  call(f_89ba05c, 3, P.m, P.first_pt, fbits(speed));
  if (P.manual) { /* the lever to the gear SetFirstPos chose (CTransmission::SetFirst) */
    int g = (int)M32(P.m + M_ENGINE + 0x3c);
    P.lever = g < 1 ? 0 : g - 1 > P.top_lever ? P.top_lever : g - 1;
  }
  read_body(c); /* car_update's displacement from here */
  c->steer = 0;
}

static void first_frame(car_state *c) {
  memset(c, 0, sizeof *c);
  /* the rolling start is at about 120 km/h: second gear */
  P.lever = 1;
  read_body(c);
  read_camera(c);
  read_jct_blocks(c);
  read_traffic(c);
  read_rival(c);
#ifdef WMMT_EGL
  if (!PG.requested && getenv("WMMT_TA_GOAL")) { /* test: the checkpoints and the goal (car_start) within this many m */
    uint32_t tk = M32(TIME_KEEPER_PTR);
    int n = tk ? (int)M32(tk + TK_COUNT) : 0;
    float len = 1000.0f * (float)atof(getenv("WMMT_TA_GOAL"));
    for (int k = 1; k < n; ++k) WF(M32(tk + TK_ODO) + 4u * (uint32_t)k, COURSES[P.course].dist + len * (float)k / (float)(n - 1));
  }
  if (!PG.requested && getenv("WMMT_TA_TIME")) WF(RACE_TIME_LEFT, (float)atof(getenv("WMMT_TA_TIME"))); /* test: the time to start with */
#endif
  read_race(&c->race);
  c->manual = P.manual;
  c->gear = P.manual ? 2 : 1;
  c->on_ground = 1;
}

float car_kmh(const car_state *c) { return fabsf(c->speed) * 3.6f; }

/* CInfoSEMc events are sampled at physics rate, not rendering rate. */
static void read_se(car_se *out) {
  static unsigned rev_sequence;
  uint32_t se = P.m + 0xb88u;
  /* CInfoSEMc::Init sets +0x1d from settings+0x73; +0x84 is the
   * reactive envelope, not the adjacent +0x1e instantaneous state. */
  out->rev_enabled = M8(se + 0x1du) != 0;
  out->rev_vol = MF(se + 0x84u);
  if (++rev_sequence == 0) ++rev_sequence;
  out->rev_sequence = rev_sequence;
  if (M8(se + 0xa8u)) {
    out->valb = 1;
    out->valb_vol = MF(se + 0xacu);
  }
  int backfire = M8(se + 0xb0u) != 0;
  if (backfire && !P.se_backfire_on) {
    out->backfire = 1;
    out->backfire_vol = MF(se + 0xb4u);
    out->backfire_hz = (float)(int32_t)M32(se + 0xb8u);
  }
  P.se_backfire_on = backfire;
  /* Set_SE_Effect_Reactive selects CheckZebra or CheckGapEff. Mc_Req
   * maps this request to original one-shot 3 (gyap.wav). */
  if (M8(se + 0xbcu)) {
    out->road_hz = (int32_t)M32(se + 0xc4u);
    out->road_vol = MF(se + 0xc0u);
  }
}

static void read_engine_se(car_engine_se *out) {
  uint32_t se = P.m + 0xb88u;
  /* CSE::Mc_Req reads the native gain and normalized RPM here. The shift
   * requests can arrive in any of the physics steps before snd_update. */
  out->gain = MF(se + 0x68u);
  out->rpm = MF(se + 0x6cu);
  out->accel = M8(se + 0x24u) != 0;
  out->shift_down |= M8(se + 0x72u) != 0;
  out->shift_up |= M8(se + 0x73u) != 0;
}

/* CSeq::Exec samples the player's SHitPushBack records (0x8984c87).
 * The pinned recompiled object stubs the original logger bodies. */
static void read_vs_drive_style(void) {
  uint32_t wall = P.m + 0xd4u, contact = P.m + 0x90u;
  if (M8(wall) && !M8(wall + 1u)) {
    float force = MF(wall + 0x3cu);
    if (isfinite(force)) P.drive_style.wall_force += force;
    ++P.drive_style.wall_ticks;
  }
  int hit = M8(contact) != 0, kind = (int32_t)M32(contact + 4u);
  float force = 0;
  if (hit && kind <= 3 && kind <= P.drive_style.last_kind) {
    float velocity[3], facing[3], push[3];
    for (unsigned i = 0; i < 3; ++i) {
      velocity[i] = MF(P.m + 0xab0u + 4u * i);
      facing[i] = MF(P.m + 0xa0cu + 4u * i);
      push[i] = MF(contact + 0x30u + 4u * i);
    }
    float speed = sqrtf(v3_dot(velocity, velocity)), magnitude = MF(contact + 0x3cu);
    if (speed > 10000.0f) {
      float direction = magnitude > 0.01f ? v3_dot(facing, push) / magnitude : 0;
      force = fmaxf(0, -v3_dot(velocity, push) / speed) * (0.2f + 0.8f * fabsf(direction));
    }
  }
  mileage_style_contact(&P.drive_style, hit, kind, isfinite(force) ? force : 0);
}

unsigned car_vs_drive_style(unsigned previous) {
  return P.vs_race ? mileage_style_commit(previous, &P.drive_style) : previous;
}

void car_update(car_state *c, const car_input *in) {
  if (!P.ready) return;
  if (PG.arcade_on && PG.observation.status==CAR_GHOST_FINISHED &&
      !ghost_crown_running_out() &&
      (!PG.config.record_player || PG.saved || !PG.observation.goal_reached || PG.observation.export_ready ||
       PG.observation.native_ticks - PG.observation.finish_tick >=
         (PG.config.race_field[0] == GHOST_LONG_TA_STAGE ? 9u : 6u))) return;
  /* digital buttons: the arcade expects a wheel, so stand in for the driver's hands.
   * Turn in at a steady rate and centre faster, to full lock at any speed as the cabinet's
   * wheel goes; the tilt is a wheel already, followed closely */
  float target = in->steer;
  float rate = in->analog ? 12.0f : fabsf(target) > fabsf(c->steer) && target * c->steer >= 0 ? 3.0f : 8.0f;
  float ds = target - c->steer;
  if (ds > rate / 60.0f) ds = rate / 60.0f;
  if (ds < -rate / 60.0f) ds = -rate / 60.0f;
  c->steer += ds;

  /* clGameInput for CIO::Drive: wheel, pedals and the shift lever (gear - 1, -1 = neutral).
   * With AT the arcade ignores the lever. */
  if (P.manual) {
    if (in->shift_up && P.lever < P.top_lever) P.lever++;
    if (in->shift_down && P.lever > -1) P.lever--;
  }
  WF(P.gin, c->steer);
#ifdef WMMT_EGL
  if (getenv("WMMT_PILOT")) { /* test: the arcade's own pilot (CMcPilot) steers, flat out */
    uint32_t pilot = M32(0x98028dcu);
    W32(pilot, M32(0x9802924u));
    W32(pilot + 4, M32(0x9802928u));
    call(f_89bcca8, 2, pilot, P.m);
    WF(P.gin, -MF(pilot + 0x14));
  }
#endif
  WF(P.gin + 4, in->throttle);
  WF(P.gin + 8, in->brake);
  /* clGameInput+0xc is the arcade intrusion trigger. CSeq mode 5 copies it
   * to CIO+0x11 for CPassing; the resulting lamp bit is already in SLxPacket. */
  W8(P.gin + 0x0c, P.vs_race && c->race.play_state == 2 && !c->race.over && in->passing);
  W32(P.gin + 0x14, P.manual ? (uint32_t)P.lever : 0xffffffffu);
  /* the arcade frame: the traffic's AI and life, the car, what everything hit, the
   * checkpoints and the time, the sounds' cues */
  /* Exec advances nCnt even if CLinx has not accepted the frame. Use its
   * initialization and ACK gates so a stalled link cannot repeat a hit. */
  int style_tick = P.vs_race && M8(0x9802970u) && (call(f_89ebd5c, 0) & 255);
  call(f_8983f64, 1, P.gin_ptr);
  if (style_tick) read_vs_drive_style();
  if (PG.started) PG.observation.native_ticks++;
  read_se(&c->se);
  read_engine_se(&c->engine_se);
  c->rev_lamp_frame = (int32_t)M32(0x9802828u); /* CSeq::nCnt, observation only */

  float prev[3] = { c->pos[0], c->pos[1], c->pos[2] };
  float prev_speed = c->speed;
  read_body(c);
  read_camera(c);
  read_jct_blocks(c);
  read_traffic(c);
  read_rival(c);
  read_race(&c->race);
  ghost_observe();
  /* velocity from the frame's displacement (display units per frame -> m/s) */
  float v[3] = { (c->pos[0] - prev[0]) * 6.0f, (c->pos[1] - prev[1]) * 6.0f, (c->pos[2] - prev[2]) * 6.0f };
  const float *M = c->body;
  c->speed = v[0] * M[8] + v[1] * M[9] + v[2] * M[10];
  float lateral = v[0] * M[0] + v[1] * M[1] + v[2] * M[2];

  c->rpm = MF(P.m + M_ENGINE + 8) * (60.0f / 6.2831853f);
  /* CEngine::GetRevRate: rpm over the engine's rev limit (its parameters' +0x8c) */
  float limit = MF(M32(P.m + M_ENGINE) + 0x8c);
  c->rev_rate = limit > 0 ? fminf(1.0f, fmaxf(0.0f, c->rpm / limit)) : 0;
  c->boost = MF(P.m + M_TURBO + 4);
  int gear = (int)M32(P.m + M_ENGINE + 0x3c);
  if (gear != c->gear && c->gear) c->shift_event = gear > c->gear ? 1 : -1;
  c->gear = gear;

  /* effect cues: squeal from sideways speed, impact from a sudden loss of speed */
  float squeal = fminf(1.0f, fmaxf(0.0f, (fabsf(lateral) - 1.5f) / 5.0f));
  if (in->brake > 0.5f && fabsf(c->speed) > 15.0f) squeal = fmaxf(squeal, 0.7f * in->brake);
  c->slip += (squeal - c->slip) * 0.15f;
  float lost = fabsf(prev_speed) - fabsf(c->speed);
  c->wall_hit = fmaxf(0.0f, c->wall_hit - 1.0f / 60.0f);
  if (hits) {
    /* the frame's change of velocity across the ground, past what the tyres do (about 1.5 g,
     * 0.25 m/s a frame; a hard corner flat out comes to 0.4 on the Mi 6's log). Sliding along
     * a wall at 120 km/h bounces 0.5..0.7 m/s a frame: the wall's loop; a crash (snd_update's
     * from impact 6) from 0.8 m/s, a car's or a wall's hit */
    float dx = v[0] - c->vel[0], dz = v[2] - c->vel[2], dv = sqrtf(dx * dx + dz * dz);
    if (c->vel_ok && dv > 0.5f) c->wall_hit = 0.3f;
    if (c->vel_ok && dv > 0.8f) c->impact = fmaxf(c->impact, dv * 12.0f);
    /* the arcade's scrape: the wall's loop while it lasts, a light crash as it starts after
     * half a second clear (it flickers on and off along a wall) */
    if (c->effect.spark > 0.0f) {
      c->wall_hit = fmaxf(c->wall_hit, 0.2f);
      if (!c->sparked) c->impact = fmaxf(c->impact, 7.0f);
    }
    c->sparked = c->effect.spark > 0.0f ? SPARK_CLEAR : c->sparked > 0 ? c->sparked - 1 : 0;
    memcpy(c->vel, v, sizeof c->vel);
    c->vel_ok = 1;
  } else if (lost > 0.4f) { /* beyond what the brakes do (about 1.5 g = 0.25 m/s per frame) */
    c->impact = fmaxf(c->impact, lost * 4.0f);
    c->wall_hit = 0.3f;
  }
}

/* Native TA timing snapshot: no game calls, native-memory writes, or RNG mutation. */
static int ta_ranking_heap_span(uint32_t p, size_t bytes) {
  return rc_mem && p >= RC_HEAP_BASE && p <= rc_heap_next &&
         rc_heap_next <= RC_HEAP_BASE + RC_HEAP_SIZE && bytes <= (size_t)(rc_heap_next - p);
}
int car_ta_ranking_info(car_ta_ranking_observation *out) {
  if (out) memset(out, 0, sizeof *out);
  if (!out || !P.ready || !rc_mem || PG.requested || PG.started || PG.arcade_on || movie ||
      P.has_rival || P.ten_stage || P.vs_on || P.vs_race || P.course < 0 || P.course >= CAR_COURSES) return 0;
  uint32_t cfg = M32(0x9802968u), tk = M32(TIME_KEEPER_PTR), state = M32(STATE);
  if (!ta_ranking_heap_span(cfg, 0x200u) || !ta_ranking_heap_span(tk, 0x18u) ||
      !ta_ranking_heap_span(P.info_race, 0x10u) || !ta_ranking_heap_span(P.m, M_ENGINE + 0x38u) ||
      M32(MACHINE_PTR) != P.m || M32(cfg + CFG_MODE) != MODE_TIME_ATTACK ||
      (state != 0u && state != 1u && state != 2u && state != 7u && state != 8u) ||
      M32(cfg + CFG_CAR) != P.spec.type || M32(cfg + CFG_POWER) != (uint32_t)P.spec.power ||
      M32(cfg + CFG_HANDLING) != (uint32_t)P.spec.handling ||
      (P.manual != 0 && P.manual != 1) || M32(P.m + M_ENGINE + 0x34u) != (P.manual ? 0u : 1u) ||
      P.spec.gears < 1 || P.spec.gears > 6 || P.spec.power < 0 || P.spec.power > CAR_TUNE_MAX ||
      P.spec.handling < 0 || P.spec.handling > CAR_TUNE_MAX ||
      M32(cfg + CFG_TA_TRAFFIC) > 1u) return 0;
  for (int i = 0; i < 6; ++i) if (!isfinite(P.spec.tyres[i])) return 0;
  if (P.spec.tyres[1] <= 0.0f || P.spec.tyres[4] <= 0.0f) return 0;
  uint32_t field[6]; memcpy(field, VA(cfg + RACE_FIELD), sizeof field);
  uint32_t slot = COURSES[P.course].stage - TA_STAGE0;
  if (slot >= 15u || !carry_image_span(TA_LENGTHS + slot * 8u, 8u) ||
      field[0] != COURSES[P.course].stage || field[1] || field[2] != COURSES[P.course].area ||
      field[3] != fbits(COURSES[P.course].dist) ||
      field[4] != fbits(COURSES[P.course].dist + MF(TA_LENGTHS + slot * 8u + 4u)) || field[5]) return 0;
  uint32_t count = M32(tk + TK_COUNT), next = M32(tk + TK_NEXT), times = M32(tk + TK_SPLIT);
  if (count < 2u || count > CAR_SECTIONS + 1u || next > count ||
      !ta_ranking_heap_span(times, (size_t)count * 4u) ||
      !isfinite(MF(P.info_race + 8u)) || MF(P.info_race + 8u) < 0.0f) return 0;
  for (uint32_t i = 0; i < next; ++i)
    if (!isfinite(MF(times + i * 4u)) || MF(times + i * 4u) < 0.0f ||
        (i && MF(times + i * 4u) < MF(times + (i - 1u) * 4u))) return 0;
  if (state == 8u && (next != count || MF(P.info_race + 8u) <= 0.0f ||
                     M32(P.info_race + 8u) != M32(times + (count - 1u) * 4u))) return 0;
  car_ta_ranking_observation o = {0};
  o.abi_version = CAR_TA_RANKING_ABI_VERSION; o.native_mode = MODE_TIME_ATTACK;
  o.native_state = state; o.goal = state == 8u;
  o.course = P.course; o.course_id = car_course_id(P.course); o.ta_slot = (int)slot;
  o.city = car_area_city((int)field[2]); o.traffic = (int)M32(cfg + CFG_TA_TRAFFIC); o.manual = P.manual;
  o.owner = P.spec; memcpy(o.race_field, field, sizeof field);
  o.elapsed_bits = M32(P.info_race + 8u); o.countdown_bits = M32(P.info_race);
  o.time_left_bits = M32(P.info_race + 4u); o.checkpoint_count = count; o.checkpoint_next = next; o.split_count = next;
  for (uint32_t i = 0; i < next; ++i) o.split_bits[i] = M32(times + 4u * i);
  *out = o; return 1;
}
