// One dimension of the execution rubric: how the program runs, as a level on
// 0..max, drawn as the same board row as a goal. The rubric is still being
// checked by people upstream, so it is labelled provisional and never reads as
// a grade.
import { Tag } from "@carbon/react";
import { WarningAlt } from "@carbon/icons-react";
import { Pips } from "./marks";
import { GoalFacts, GoalReading } from "./Reading";
import { evidenceSource, humanize, title } from "./text";

export const RubricRow = ({ d }) => {
  const labels = Array.from({ length: (d.max_level || 0) + 1 }, (_, i) => String(i));
  const chips = (
    <>
      {d.borderline && (
        <Tag
          as="span"
          size="sm"
          type="warm-gray"
          renderIcon={WarningAlt}
          title="within the borderline margin of the next level"
        >
          borderline
        </Tag>
      )}
      {d.ceiling != null && d.ceiling < d.max_level && (
        <Tag
          as="span"
          size="sm"
          type="cool-gray"
          title="the highest level this program's code can show"
        >
          code allows up to {d.ceiling}
        </Tag>
      )}
    </>
  );
  return (
    <article className="goal">
      <div className="goal-row">
        <div className="goal-name">
          <h4>{title(d.dimension)}</h4>
        </div>
        {d.level == null ? (
          <GoalReading
            labels={labels}
            reached={-1}
            none={`can't tell - ${humanize(d.u_reason)}`}
            chips={chips}
          />
        ) : (
          <div className="goal-reading">
            <p className="goal-now">
              <Pips n={labels.length} reached={d.level} />
              <strong>level {d.level}</strong>
              <span className="goal-of">of {d.max_level}</span>
              {chips}
            </p>
          </div>
        )}
      </div>
      <GoalFacts
        facts={[
          ["based on", (d.evidence || []).map(evidenceSource).join(", ") || null],
          ["counts against", (d.negatives || []).map(evidenceSource).join(", ") || null],
        ]}
      />
    </article>
  );
};
