// Every tunable number of the game in one place (the same rules as the
// pygame version, laser_game/config.py). The camera and the silhouette grid
// are set on the Python side: coop_game/config.py and laser_web/config.py.
//
// World distances in metres (M), times in seconds (S).

export const CONFIG = {
  // ---------------------------------------------------------------- bodies
  // Used in keyboard mode; with the camera, the server sends its own grid
  GRID: { x_range: [-1.8, 1.8], height_range: [0.0, 2.4], cell: 0.03 },
  // Player 1's lane is left of this, Player 2's right of it
  LANE_SPLIT_X_M: 0.0,
  // Fewer silhouette cells than this = nobody there
  MIN_BODY_CELLS: 60,

  // ------------------------------------------------------------------ view
  // The players' plane fills the screen from floor to the grid's top, like
  // a mirror; the virtual camera stands this far in front of it
  VIEW_DISTANCE_M: 2.5,
  LASER_START_DEPTH_M: 30.0,
  // Lasers keep flying this far past the players before they vanish
  LASER_PAST_DEPTH_M: 1.8,
  // Glow: strength, radius, and the brightness (0-1) where glowing starts
  BLOOM: [0.9, 0.4, 0.55],

  // ---------------------------------------------------------------- rounds
  JOIN_HOLD_S: 1.0,
  COUNTDOWN_S: 3.0,
  DEFAULT_PLAYER_HEIGHT_M: 1.7,
  PLAYER_HEIGHT_LIMITS_M: [1.0, 2.1],
  // 1 = the first player to touch a laser loses
  LIVES: 1,
  HIT_COOLDOWN_S: 1.0,
  // Out of view this long during a round = out
  FORFEIT_S: 1.5,
  RESTART_S: 10.0,

  // ---------------------------------------------------------------- lasers
  FIRST_WAVE_DELAY_S: 1.0,
  TRAVEL_START_S: 2.4,
  TRAVEL_MIN_S: 1.0,
  TRAVEL_SPEEDUP_S: 0.05,
  SPAWN_GAP_START_S: 2.2,
  SPAWN_GAP_MIN_S: 0.8,
  SPAWN_SPEEDUP_S: 0.06,
  DIAGONAL_FROM_WAVE: 6,
  KIND_WEIGHTS: { low: 3, high: 3, aimed: 2, diagonal: 2 },

  // Fractions of each player's own height
  LOW_BEAM: 0.10,            // jump over it
  HIGH_BEAM: 0.78,           // duck under it
  DIAGONAL_BEAM: [0.12, 1.15],
  LANE_INSET_M: 0.05,

  LASER_DRAW_WIDTH_M: 0.05,
  LASER_HIT_THICKNESS_M: 0.06,

  // ------------------------------------------------------------------ hits
  MIN_HIT_CELLS: 4,
  HIT_FRAMES: 2,
  HIT_WINDOW_S: 0.15,
  DISPLAY_LAG_S: 0.08,
  FRAME_TIMEOUT_S: 0.5,
};
