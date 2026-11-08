/* Include AFTER vs_session.h and vs_vote_policy.h in APP/local host/server.
 * Exactly vs4_decision_fn. Opaque ctx unused. Pure endpoint-independent policy.
 * Command must be the current round's ADVANCE; core already fences generation.
 * R1 parent-approved overlay: TIME→TUNE freezes final legal BGM; MAP still
 * locks preview song. Original ballot/ramp tables remain unchanged. */
static int vs4_vote_decision(const vs4_state *state, const vs4_command *command, void *ctx) {
  (void)ctx;
  if (!state || !command || command->op != VS4_ADVANCE || state->n < 2 || state->n > VS4_PLAYERS) return 0;
  uint16_t choice[VS4_PLAYERS];
  for (unsigned i = 0; i < state->n; ++i) choice[i] = state->members[i].choice;
  int value;
  if (state->phase == VS4_MAP) {
    return command->target == VS4_TIME &&
      vs_vote_area_result(choice, state->n, state->ready, (uint8_t)state->seed, &value) &&
      command->ramp == vs_vote_ramp_for_area(value, state->seed) &&
      command->km == state->km && command->song == state->song && command->zone == state->zone;
  }
  if (state->phase == VS4_TIME) {
    return command->target == VS4_TUNE &&
      vs_vote_day_result(choice, state->n, state->ready, &value) && command->zone == value &&
      command->ramp == state->ramp && command->km == state->km &&
      command->song >= 1 && command->song <= 22 && command->song != 2; /* R1: final BGM on TIME commit */
  }
  return 0;
}
