import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react";

// Mock the shared axios instance so the component talks to canned data, not a
// real server. Each GET resolves by URL; POSTs are spies we assert on.
vi.mock("./api", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
import api from "./api";
import CohortDashboard, { COMPACT_TAIL } from "./CohortDashboard.jsx";

const ROUTES = {
  "/api/student_states/": {
    students: [
      {
        studentID: "alice",
        classCode: "C1",
        run_count: 4,
        event_count: 12,
        last_seen: new Date().toISOString(),
        runs: { runs: [], run_count: 0 },
        episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
      },
    ],
    student_count: 1,
  },
  "/api/tracked/": {
    tracked: [
      { studentID: "alice", backfilled: true, has_data: true, present: true, picked: false },
    ],
    count: 1,
  },
  "/api/triggers/": { triggers: [], active_count: 0, counts: {} },
  "/api/polling/": { enabled: true },
  "/api/triggers/config/": {
    enabled: {
      wheel_spin: true,
      resilience: true,
      inactive: true,
      explorer: true,
      iterative: true,
    },
    labels: {},
  },
};

beforeEach(() => {
  api.get.mockImplementation((url) => Promise.resolve({ data: ROUTES[url] ?? {} }));
  api.post.mockResolvedValue({ data: {} });
});

describe("CohortDashboard", () => {
  it("renders a card with the active trigger as its status badge", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 1,
                studentID: "alice",
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "6 identical reruns",
                active: true,
                age_seconds: 42,
              },
            ],
            active_count: 1,
            counts: { wheel_spin: 1 },
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // 'alice' shows in both the roster chip and the cohort card
    expect((await screen.findAllByText("alice")).length).toBeGreaterThanOrEqual(1);
    // an active wheel_spin trigger => the Wheel-spinning status badge (card + alert)
    expect(await screen.findAllByText(/Wheel-spinning/)).not.toHaveLength(0);
  });

  it("compact card shows only the most recent runs, with true run numbers", async () => {
    const total = COMPACT_TAIL + 10; // more runs/episodes than the card shows
    const runs = Array.from({ length: total }, (_, i) => ({
      index: i,
      edit_distance: i === 0 ? null : 2,
      ts: i,
    }));
    const eps = Array.from({ length: total }, (_, i) => ({
      start_idx: i,
      end_idx: i + 1,
      event_count: 1,
      episode_type: "CODE",
      soft_indices: [],
    }));
    const evs = Array.from({ length: total }, () => ({ eventType: "blockMoved" }));
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/") {
        return Promise.resolve({
          data: {
            students: [
              {
                studentID: "alice",
                run_count: total,
                event_count: total,
                last_seen: new Date().toISOString(),
                runs: { runs, run_count: total },
                episodes: { events: evs, episodes: eps, pauses: [], event_count: total },
              },
            ],
            student_count: 1,
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    await waitFor(() =>
      expect(document.querySelectorAll('[title^="Run #"]').length).toBeGreaterThan(0),
    );
    const blocks = document.querySelectorAll('[title^="Run #"]');
    expect(blocks).toHaveLength(COMPACT_TAIL); // runs capped at the tail
    expect(blocks[blocks.length - 1].getAttribute("title")).toMatch(new RegExp(`^Run #${total} `)); // newest = true number
    expect(blocks[0].getAttribute("title")).toMatch(
      new RegExp(`^Run #${total - COMPACT_TAIL + 1} `),
    ); // window start
    // episode track: one event tile per (1-event) episode, also capped at the tail
    expect(document.querySelectorAll('[title^="CODE | "]')).toHaveLength(COMPACT_TAIL);
  });

  it("renders one block per episode with an events + duration tooltip", async () => {
    const ep = {
      start_idx: 0,
      end_idx: 4,
      event_count: 4,
      episode_type: "CODE",
      soft_indices: [1],
      start_ts: 0,
      end_ts: 45,
    };
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/") {
        return Promise.resolve({
          data: {
            students: [
              {
                studentID: "alice",
                current_state: 1,
                current_label: "explorer",
                stuck: false,
                consecutive_stuck: 0,
                run_count: 0,
                event_count: 4,
                last_seen: new Date().toISOString(),
                state_sequence: [],
                hmm: { runs: [], run_count: 0, obs_labels: {} },
                episodes: { events: [], episodes: [ep], pauses: [], event_count: 4 },
              },
            ],
            student_count: 1,
            stuck_count: 0,
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    const blocks = await screen.findAllByTitle(/^CODE \| /);
    expect(blocks).toHaveLength(1); // one block, not per-event
    expect(blocks[0].getAttribute("title")).toBe("CODE | 4 events | 45s");
  });

  it("surfaces a backend alert in the intervention column", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 1,
                studentID: "alice",
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "3 re-runs",
                active: true,
                age_seconds: 42,
              },
            ],
            active_count: 1,
            counts: { wheel_spin: 1 },
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // an alert row renders its own dismiss (✕) button -- proof the alert surfaced
    expect(await screen.findByTitle(/Dismiss alert/)).toBeInTheDocument();
  });

  it("suppresses alerts for a student marked absent", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/tracked/") {
        return Promise.resolve({
          data: {
            tracked: [
              {
                studentID: "alice",
                backfilled: true,
                has_data: true,
                present: false,
                picked: false,
              },
            ],
            count: 1,
          },
        });
      }
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 1,
                studentID: "alice",
                trigger_type: "inactive",
                label: "Inactive",
                value: "6m idle",
                active: true,
                age_seconds: 360,
              },
            ],
            active_count: 1,
            counts: { inactive: 1 },
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // the absent kid's alert is filtered out -> empty column, no dismiss button
    expect(await screen.findByText(/No active alerts/)).toBeInTheDocument();
    expect(screen.queryByTitle(/Dismiss alert/)).toBeNull();
  });

  it("posts a roster pick (source roster, no trigger) from the student card", async () => {
    render(<CohortDashboard />);
    const pick = await screen.findByText("Mark picked");
    fireEvent.click(pick);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/picked/", {
        studentID: "alice",
        picked: true,
        source: "roster",
        trigger_id: null,
        trigger_type: null,
      });
    });
  });

  it('stamps the trigger when "Picked" is clicked on an alert card', async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 9,
                studentID: "alice",
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "6 identical reruns",
                active: true,
                age_seconds: 42,
              },
            ],
            active_count: 1,
            counts: { wheel_spin: 1 },
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // Both the card and the alert say "Mark picked"; click the one in the alert feed.
    const feed = await screen.findByRole("complementary", { name: "Needs intervention" });
    fireEvent.click(await within(feed).findByText("Mark picked"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/picked/", {
        studentID: "alice",
        picked: true,
        source: "intervention",
        trigger_id: 9,
        trigger_type: "wheel_spin",
      });
    });
  });

  it("toggles daemon polling via the pause button", async () => {
    render(<CohortDashboard />);
    const pause = await screen.findByText(/Pause polling/);
    fireEvent.click(pause);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/polling/", { enabled: false });
    });
  });

  it("background polling never reverts the pause toggle (it is fetched once, not polled)", async () => {
    vi.useFakeTimers();
    try {
      // server reports "on"; the POST hangs so the click stays applied optimistically
      api.get.mockImplementation((url) =>
        Promise.resolve({
          data: url === "/api/polling/" ? { enabled: true } : (ROUTES[url] ?? {}),
        }),
      );
      api.post.mockImplementation(() => new Promise(() => {})); // never resolves
      render(<CohortDashboard />);
      await act(() => vi.advanceTimersByTimeAsync(0)); // mount fetch -> "on"

      fireEvent.click(screen.getByText(/Pause polling/)); // optimistic -> off
      expect(screen.getByText(/Resume polling/)).toBeInTheDocument();

      // advance well past several poll intervals: the other feeds re-poll, but the
      // pause state is NOT on a timer, so nothing can flip it back to "on".
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(screen.getByText(/Resume polling/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("acks a trigger when its ✕ is clicked", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 7,
                studentID: "alice",
                trigger_type: "inactive",
                label: "Inactive",
                value: "idle 6m",
                active: true,
                age_seconds: 360,
              },
            ],
            active_count: 1,
            counts: {},
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle(/Dismiss alert/));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/triggers/ack/", { id: 7 });
    });
  });

  it("keeps recently-resolved alerts in the feed (they linger ~2 min)", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              // a recovered wheel_spin still in the backend's 2-min window -> still shows
              {
                id: 1,
                studentID: "alice",
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "6 identical reruns",
                active: false,
                age_seconds: 30,
              },
              {
                id: 2,
                studentID: "alice",
                trigger_type: "explorer",
                label: "Explorer",
                value: "changed 15",
                active: false,
                age_seconds: 5,
              },
            ],
            active_count: 0,
            counts: {},
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    // both linger in the feed -> two alert rows
    await waitFor(() => expect(screen.getAllByTitle(/Dismiss alert/)).toHaveLength(2));
  });

  it("opens the detail modal and fetches the heavy payload on click", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/") {
        return Promise.resolve({
          data: {
            studentID: "alice",
            current_state: 2,
            run_count: 4,
            event_count: 12,
            block: { llm_prompt: "[Active] events_whenStarted", timestamp: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
            hmm: { runs: [], run_count: 0, obs_labels: {} },
          },
        });
      }
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice")); // the card's id label
    expect(await screen.findByText("LLM prompt")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/student_states/alice/"));
  });

  it("renders per-run goal evidence with rungs and uncertainty flags", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/") {
        return Promise.resolve({
          data: {
            studentID: "alice",
            run_count: 1,
            event_count: 3,
            block: { llm_prompt: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
            runs: { runs: [], run_count: 0 },
            goal_recognition_enabled: true,
            goal_runs: [
              {
                index: 0,
                playground: "castle_crashers",
                status: "profiled",
                goals: [
                  {
                    goal: "clear_debris_zone",
                    indicators: [
                      {
                        name: "debris_zone_coverage",
                        role: "intent",
                        channel: "code",
                        rung: "negligible",
                        rung_labels: ["negligible", "some", "meaningful", "systematic"],
                        direction: "higher_is_better",
                        abstained: false,
                        abstain_reason: null,
                        flags: [],
                      },
                      {
                        name: "plow_proximity_execution",
                        role: "attainment",
                        channel: "simulation",
                        rung: null,
                        rung_labels: ["attach_estimated", "armed_never_close"],
                        direction: "lower_is_better",
                        abstained: true,
                        abstain_reason: "no_simulation",
                        flags: ["sim_unverified"],
                      },
                    ],
                  },
                ],
              },
            ],
          },
        });
      }
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice"));
    expect(await screen.findByText("Goal evidence")).toBeInTheDocument();
    expect(await screen.findByText("Clear debris zone")).toBeInTheDocument();
    // the rung ladder: the reached rung and an un-reached rung both render as segments
    expect(await screen.findByText("negligible")).toBeInTheDocument();
    expect(await screen.findByText("systematic")).toBeInTheDocument();
    // an abstained indicator states no reading (with the reason), never a rung
    expect(await screen.findByText(/no reading - no simulation/)).toBeInTheDocument();
    expect(await screen.findByText("sim unverified")).toBeInTheDocument(); // an uncertainty flag chip
    // achieved/attempting grouping and the single-run label
    expect(await screen.findByText("achieved")).toBeInTheDocument();
    expect(await screen.findByText("attempting")).toBeInTheDocument();
    expect(await screen.findByText("Run 0")).toBeInTheDocument();
  });

  it("surfaces run-level outputs: left-the-island, fidelity, diagnostics", async () => {
    const runs = [
      {
        index: 0,
        playground: "castle_crashers",
        status: "profiled",
        diagnostics: ["invalid_timestamp", "inherited_playground"],
        summary: {
          boundary_exceeded: true,
          boundary_exit_step: 3,
          boundary_exit_overridden: false,
          outcome_available: false,
          fidelity_verdict: "agree",
          fabricated_motion: false,
        },
        goals: [
          {
            goal: "remain_on_island",
            indicators: [
              {
                name: "on_island_sim",
                role: "attainment",
                channel: "simulation",
                rung: "off_island",
                rung_labels: ["unknown", "off_island", "on_island"],
                direction: null,
                abstained: false,
                abstain_reason: null,
                flags: [],
              },
            ],
          },
        ],
      },
    ];
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/")
        return Promise.resolve({
          data: {
            studentID: "alice",
            block: { llm_prompt: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
            runs: { runs: [], run_count: 0 },
            goal_recognition_enabled: true,
            goal_runs: runs,
          },
        });
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice"));
    const chip = await screen.findByText(/left the island/);
    expect(chip.textContent).toContain("step 3"); // critical failure surfaced with the exit step
    expect(await screen.findByText(/sim vs GPS agree/)).toBeInTheDocument();
    expect(await screen.findByText("invalid timestamp")).toBeInTheDocument(); // a diagnostic chip
    expect(screen.queryByText("inherited playground")).toBeNull(); // routine bookkeeping, hidden
  });

  it("renders the goal claims, rubric, timeline and family-grouped battery", async () => {
    const runs = [
      {
        index: 0,
        playground: "castle_crashers",
        status: "profiled",
        summary: {},
        diagnostics: [],
        goals: [
          {
            goal: "clear_debris_zone",
            indicators: [
              {
                name: "weight_cleared",
                role: "attainment",
                channel: "outcome",
                rung: "med_goal",
                rung_labels: ["none", "initial_goal", "med_goal", "high_goal", "advanced_goal"],
                direction: "higher_is_better",
                value: 1600,
                abstained: false,
                abstain_reason: null,
                flags: [],
              },
            ],
          },
        ],
        timeline: {
          events: [
            {
              step: 2,
              block_type: "pg_drivetrain_drive_for",
              goal: "playground_engagement",
              indicator: "robot_moved",
              from_rung: "stationary",
              to_rung: "moved",
              flags: [],
            },
          ],
          post_exit_events: [],
          boundary_exit_step: null,
        },
        battery: {
          eligible: true,
          qualifying_blocks: ["pg_sensing_optical_near_object"],
          goal_mapping: {},
          scenarios: [
            {
              scenario_id: "t2a_direct",
              family: "t2_boundary",
              description:
                "T2 boundary response \u2014 direct \u2014 head-on arrival, block at the intersection.",
              goal: "remain_on_island",
              construct: "static",
              checks: [
                { name: "detects", status: "fail", facet: "object_detection", detail: "0mm" },
                {
                  name: "stays_on_island",
                  status: "abstained",
                  abstained: true,
                  abstain_reason: "encounter_not_reached",
                },
              ],
            },
            {
              scenario_id: "t1_castle_wall",
              family: "t1_debris_field",
              goal: "clear_debris_zone",
              construct: "static",
              checks: [{ name: "proportion_cleared", status: "measured", value: 0.25 }],
            },
          ],
        },
        rollup: {
          provisional: false,
          goals: [
            {
              goal: "remain_on_island",
              source: "battery",
              rung: "boundary_safe",
              rungs: ["boundary_unsafe", "condition_dependent", "boundary_safe"],
              certainty: "reduced",
              certainty_reasons: ["sparse_evidence"],
              n_valid: 3,
              n_abstained: 16,
              flags: [],
            },
            {
              goal: "engage_plow",
              source: "profile_derived",
              rung: "approached_not_armed",
              rungs: ["not_pursued", "approached_not_armed", "armed_not_attached", "attached"],
              basis: { plow_approach_intent: "near" },
            },
          ],
        },
        rubric: {
          provisional: true,
          status: "provisional_stage2E",
          dimensions: [
            {
              dimension: "control_structure",
              level: 2,
              max_level: 3,
              borderline: true,
              ceiling: null,
              evidence: ["production.coordination_relations"],
              negatives: [],
            },
            {
              dimension: "environmental_feedback",
              level: null,
              max_level: 2,
              u_reason: "no_informative_variable",
              evidence: [],
              negatives: [],
            },
          ],
        },
      },
    ];
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/")
        return Promise.resolve({
          data: {
            studentID: "alice",
            block: { llm_prompt: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
            runs: { runs: [], run_count: 0 },
            goal_recognition_enabled: true,
            goal_runs: runs,
          },
        });
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice"));
    // timeline: a rung transition
    expect(await screen.findByText("Goal progression")).toBeInTheDocument();
    const ev = await screen.findByText(/stationary/);
    expect(ev.textContent).toContain("moved");
    // battery: scenarios grouped by family, with named checks
    expect(await screen.findByText("Sensor test battery")).toBeInTheDocument();
    expect(await screen.findByText("T2 boundary")).toBeInTheDocument();
    expect(await screen.findByText("T1 debris field")).toBeInTheDocument();
    expect(await screen.findByText("t2a direct")).toBeInTheDocument();
    // the card's family/variant prefix is trimmed from the scenario blurb
    expect(
      await screen.findByText("head-on arrival, block at the intersection."),
    ).toBeInTheDocument();
    expect(await screen.findByText("detects")).toBeInTheDocument();
    // an abstained check says why; a measured check carries its value
    expect(
      await screen.findByTitle("stays on island: abstained: encounter not reached"),
    ).toBeInTheDocument();
    expect(await screen.findByText("25%")).toBeInTheDocument();
    // goal claims: a banded goal on its ladder, with the certainty demotion shown
    expect(await screen.findByText("Goal claims")).toBeInTheDocument();
    expect(await screen.findByText("boundary safe")).toBeInTheDocument();
    expect(await screen.findByText("sparse evidence")).toBeInTheDocument();
    expect(await screen.findByText("3 valid, 16 abstained")).toBeInTheDocument();
    // ...and a derived goal, read from a named indicator
    expect(await screen.findByText("approached not armed")).toBeInTheDocument();
    expect(await screen.findByText("from indicators")).toBeInTheDocument();
    expect(await screen.findByText("plow approach intent")).toBeInTheDocument();
    // rubric: labelled provisional, a level on its 0..max ladder, and a U reason
    expect(await screen.findByText("Execution rubric")).toBeInTheDocument();
    expect(await screen.findByText("provisional")).toBeInTheDocument();
    expect(await screen.findByText("borderline")).toBeInTheDocument();
    expect(await screen.findByText("code: coordination relations")).toBeInTheDocument();
    expect(await screen.findByText("undetermined - no informative variable")).toBeInTheDocument();
  });

  it("clears the previous student's goal evidence when switching students", async () => {
    const aliceRuns = [
      {
        index: 0,
        playground: "castle_crashers",
        status: "profiled",
        goals: [
          {
            goal: "clear_debris_zone",
            indicators: [
              {
                name: "weight_cleared",
                role: "attainment",
                channel: "outcome",
                rung: "med_goal",
                rung_labels: ["none", "initial_goal", "med_goal", "high_goal", "advanced_goal"],
                direction: "higher_is_better",
                value: 1600,
                abstained: false,
                abstain_reason: null,
                flags: [],
              },
            ],
          },
        ],
      },
    ];
    const roster = (ids) => ({
      tracked: ids.map((studentID) => ({
        studentID,
        backfilled: true,
        has_data: true,
        present: true,
        picked: false,
      })),
      count: ids.length,
    });
    const lightCard = (studentID) => ({
      studentID,
      classCode: "C1",
      run_count: 1,
      event_count: 3,
      last_seen: new Date().toISOString(),
      runs: { runs: [], run_count: 0 },
      episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
    });
    const heavy = (studentID, goal_runs) => ({
      studentID,
      block: { llm_prompt: null },
      episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
      runs: { runs: [], run_count: 0 },
      goal_recognition_enabled: true,
      goal_runs,
    });
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/")
        return Promise.resolve({
          data: { students: [lightCard("alice"), lightCard("bob")], student_count: 2 },
        });
      if (url === "/api/tracked/") return Promise.resolve({ data: roster(["alice", "bob"]) });
      if (url === "/api/student_states/alice/")
        return Promise.resolve({ data: heavy("alice", aliceRuns) });
      if (url === "/api/student_states/bob/") return Promise.resolve({ data: heavy("bob", []) }); // bob has no goal runs
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice"));
    expect(await screen.findByText("Clear debris zone")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("bob")); // switch students
    // alice's goal must clear out, and bob's empty state must show
    await waitFor(() => expect(screen.queryByText("Clear debris zone")).toBeNull());
    expect(await screen.findByText(/No Castle Crashers runs profiled yet/)).toBeInTheDocument();
  });

  it("toggles a trigger type from the Triggers panel", async () => {
    // the POST echoes the new enabled map back, which the component stores
    api.post.mockResolvedValue({
      data: {
        enabled: {
          wheel_spin: false,
          resilience: true,
          inactive: true,
          explorer: true,
          iterative: true,
        },
      },
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Triggers/)); // open the panel
    const offButtons = await screen.findAllByText("On");
    fireEvent.click(offButtons[0]); // turn the first one off
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/triggers/config/",
        expect.objectContaining({ enabled: false }),
      ),
    );
  });

  it("downloads a zip snapshot", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    api.post.mockResolvedValue({
      data: new Blob(["x"], { type: "application/zip" }),
      headers: { "content-disposition": 'attachment; filename="snap.zip"' },
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Export/));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/export/", null, { responseType: "blob" }),
    );
    await waitFor(() => expect(click).toHaveBeenCalled());
  });

  it("does not poll while the tab is hidden (Page Visibility gate)", async () => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    try {
      render(<CohortDashboard />);
      // The once-on-mount controls still load (they aren't gated)...
      await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/polling/"));
      // ...but none of the visibility-gated poll loops ever fire.
      const polled = (url) => api.get.mock.calls.some(([u]) => u === url);
      expect(polled("/api/student_states/")).toBe(false);
      expect(polled("/api/tracked/")).toBe(false);
      expect(polled("/api/triggers/")).toBe(false);
    } finally {
      Object.defineProperty(document, "hidden", { configurable: true, value: false });
    }
  });

  it("resets after confirmation", async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Reset/));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/reset/"));
  });

  it("warns and keeps data when reset fails", async () => {
    api.post.mockImplementation((url) =>
      url === "/api/reset/" ? Promise.reject(new Error("boom")) : Promise.resolve({ data: {} }),
    );
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Reset/));
    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("Reset failed")),
    );
  });

  it('shows "waiting for activity" for a tracked student with no state yet', async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/tracked/") {
        return Promise.resolve({
          data: {
            tracked: [
              {
                studentID: "newkid",
                backfilled: false,
                has_data: false,
                present: true,
                picked: false,
              },
            ],
            count: 1,
          },
        });
      }
      if (url === "/api/student_states/") {
        return Promise.resolve({ data: { students: [], student_count: 0, stuck_count: 0 } });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    expect(await screen.findByText(/Waiting for activity/)).toBeInTheDocument();
  });

  it("tracks a semicolon-separated list, ignoring whitespace and blanks/dupes", async () => {
    render(<CohortDashboard />);
    const input = await screen.findByPlaceholderText(/Track student IDs/);
    fireEvent.change(input, { target: { value: " alice ;bob; ;  carol ; bob " } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => {
      const tracked = api.post.mock.calls
        .filter(([url]) => url === "/api/tracked/")
        .map(([, body]) => body.studentID);
      expect(new Set(tracked)).toEqual(new Set(["alice", "bob", "carol"])); // blank + dup dropped
    });
  });

  it("untracks a student from the roster chip", async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("Stop tracking"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/tracked/", { studentID: "alice", remove: true }),
    );
  });

  it("closes the detail modal if the open student is untracked", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/") {
        return Promise.resolve({
          data: {
            studentID: "alice",
            current_state: 1,
            run_count: 0,
            event_count: 0,
            block: { llm_prompt: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
            hmm: { runs: [], run_count: 0, obs_labels: {} },
          },
        });
      }
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice")); // open the modal
    await screen.findByText("LLM prompt");
    fireEvent.click(screen.getByTitle("Stop tracking")); // untrack the open student
    await waitFor(() => expect(screen.queryByText("LLM prompt")).not.toBeInTheDocument());
  });

  it('falls back to "no activity" when the detail fetch fails', async () => {
    api.get.mockImplementation((url) =>
      url === `/api/student_states/alice/`
        ? Promise.reject(new Error("404"))
        : Promise.resolve({ data: ROUTES[url] ?? {} }),
    );
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice"));
    expect(await screen.findByText(/No activity yet/)).toBeInTheDocument();
  });

  it("warns when export fails", async () => {
    api.post.mockImplementation((url) =>
      url === "/api/export/" ? Promise.reject(new Error("boom")) : Promise.resolve({ data: {} }),
    );
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Export/));
    await waitFor(() => expect(window.alert).toHaveBeenCalledWith("Export failed."));
  });

  it("toggles presence from a card", async () => {
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Present/));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/presence/", {
        studentID: "alice",
        present: false,
      }),
    );
  });

  it("adds a note from the alert editor", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 3,
                studentID: "alice",
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "2 re-runs",
                active: true,
                age_seconds: 30,
              },
            ],
            active_count: 1,
            counts: {},
          },
        });
      }
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText("Add note")); // open the editor
    const box = await screen.findByPlaceholderText(/What did you see during this alert/);
    fireEvent.change(box, { target: { value: "looks stuck on the loop" } });
    fireEvent.click(screen.getByText("Save note"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/notes/",
        expect.objectContaining({
          studentID: "alice",
          text: "looks stuck on the loop",
          trigger_id: 3,
          trigger_type: "wheel_spin",
        }),
      ),
    );
  });

  it("renders the identity-switch feed and acks a switch", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/switches/") {
        return Promise.resolve({
          data: {
            switches: [
              {
                id: 5,
                studentID: "cobra3",
                kind: "class",
                from: "FPFVDH",
                to: "AFURRR",
                ts: new Date().toISOString(),
                acknowledged: false,
              },
            ],
            unacked: 1,
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    expect(await screen.findByText(/Identity switches/)).toBeInTheDocument();
    expect(await screen.findByText("FPFVDH -> AFURRR")).toBeInTheDocument();
    fireEvent.click(await screen.findByTitle("Dismiss switch"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/switches/ack/", { id: 5 }));
  });

  it("shows the previous trigger (what and when) on an alert card", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/triggers/") {
        return Promise.resolve({
          data: {
            triggers: [
              {
                id: 2,
                studentID: "alice",
                trigger_type: "inactive",
                label: "Inactive",
                value: "idle 6m",
                active: true,
                age_seconds: 360,
                prev: {
                  trigger_type: "wheel_spin",
                  label: "Wheel-spinning",
                  at: "2026-07-21T10:24:00+00:00",
                },
              },
            ],
            active_count: 1,
            counts: { inactive: 1 },
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    expect(await screen.findByText(/Before this: Wheel-spinning/)).toBeInTheDocument();
  });

  it("renders the trigger-history grid in the detail modal", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/api/student_states/alice/") {
        return Promise.resolve({
          data: {
            studentID: "alice",
            run_count: 4,
            event_count: 12,
            block: { llm_prompt: "x", timestamp: null },
            episodes: { events: [], episodes: [], pauses: [], event_count: 0 },
          },
        });
      }
      if (url === "/api/notes/") return Promise.resolve({ data: { notes: [], count: 0 } });
      if (url === "/api/triggers/history/") {
        return Promise.resolve({
          data: {
            history: [
              {
                id: 9,
                trigger_type: "wheel_spin",
                label: "Wheel-spinning",
                value: "6 identical reruns",
                started_at: "2026-07-21T10:24:00+00:00",
                resolved_at: null,
                status: "active",
              },
              {
                id: 7,
                trigger_type: "explorer",
                label: "Explorer",
                value: "changed 21",
                started_at: "2026-07-21T10:01:00+00:00",
                resolved_at: "2026-07-21T10:01:00+00:00",
                status: "dismissed",
              },
            ],
            count: 2,
          },
        });
      }
      return Promise.resolve({ data: ROUTES[url] ?? {} });
    });
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByTitle("alice")); // open the modal
    expect(await screen.findByText("Trigger history")).toBeInTheDocument();
    expect(await screen.findByText("6 identical reruns")).toBeInTheDocument();
    expect(await screen.findByText("dismissed")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/api/triggers/history/", {
        params: { studentID: "alice" },
      }),
    );
  });

  it("a failed write retries, parks in the outbox, and toasts red", async () => {
    // Primary write always fails; the outbox endpoint still works.
    api.post.mockImplementation((url) =>
      url === "/api/outbox/"
        ? Promise.resolve({ data: { stored: true } })
        : Promise.reject(new Error("Network Error")),
    );
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Present/));
    // After both retries the raw input is parked verbatim...
    await waitFor(
      () =>
        expect(api.post).toHaveBeenCalledWith("/api/outbox/", {
          op: "absent: alice",
          payload: { studentID: "alice", present: false },
          error: "Network Error",
        }),
      { timeout: 3000 },
    );
    // ...and the failure is loud: a sticky toast naming the action.
    expect(await screen.findByText("NOT saved")).toBeInTheDocument();
    expect(screen.getByText("absent: alice")).toBeInTheDocument();
  });

  it("parks in localStorage when the outbox endpoint is down too", async () => {
    // jsdom here has no localStorage; give window a tiny in-memory one.
    const store = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (k) => store[k] ?? null,
        setItem: (k, v) => {
          store[k] = String(v);
        },
        removeItem: (k) => {
          delete store[k];
        },
      },
    });
    api.post.mockRejectedValue(new Error("Network Error")); // API fully unreachable
    render(<CohortDashboard />);
    fireEvent.click(await screen.findByText(/Present/));
    await waitFor(
      () => {
        const q = JSON.parse(store.lmdOutbox || "[]");
        expect(q).toHaveLength(1);
        expect(q[0].op).toBe("absent: alice");
      },
      { timeout: 3000 },
    );
    expect(await screen.findByText("NOT saved")).toBeInTheDocument();
  });
});
