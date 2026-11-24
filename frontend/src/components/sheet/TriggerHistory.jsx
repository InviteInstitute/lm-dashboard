// Every trigger the student has had this session, newest first. The label keeps
// its trigger colour, everything else is quiet.
import { ContainedList, ContainedListItem } from "@carbon/react";
import { Icon } from "../../icons";
import { signal, triggerMeta } from "../../lib/status";
import { clockTime } from "../../lib/time";

export const TriggerHistory = ({ history }) => (
  <ContainedList
    label={
      <>
        Trigger History {history.length > 0 && <span className="sd-count">{history.length}</span>}
      </>
    }
    kind="on-page"
    className="sd-section sd-history"
  >
    {history.length === 0 ? (
      <ContainedListItem>
        <span className="sd-empty">No triggers yet this session.</span>
      </ContainedListItem>
    ) : (
      history.map((h) => {
        const m = triggerMeta(h.trigger_type);
        const tone = signal(m.c);
        return (
          <ContainedListItem key={h.id}>
            <span className="sd-history-label" style={{ color: tone }}>
              <Icon name={m.icon} size={14} />
              {h.label}
            </span>
            <time dateTime={h.started_at} title={h.started_at}>
              {clockTime(h.started_at)}
            </time>
            <span className="sd-history-value">{h.value || "-"}</span>
            <span
              className="sd-history-status"
              style={h.status === "active" ? { color: tone } : null}
            >
              {h.status}
            </span>
          </ContainedListItem>
        );
      })
    )}
  </ContainedList>
);
