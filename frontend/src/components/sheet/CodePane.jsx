// The student's latest program, in two renderings of the same blocks behind a
// switch: a readable listing, and the compact prompt text handed to an LLM as
// context (the triggers themselves use no LLM).
import React from "react";
import { CodeSnippet, ContentSwitcher, Switch } from "@carbon/react";
import { Section } from "./Section";

const VIEWS = [
  {
    key: "readable",
    label: "Readable",
    field: "readable",
    note: "Every block with its parameters spelled out.",
    empty: "No program yet.",
  },
  {
    key: "prompt",
    label: "LLM prompt",
    field: "llm_prompt",
    note: "The same program, flattened into the compact text given to an LLM as context.",
    empty: "No prompt yet: it is built once the student runs their program.",
  },
];

export const CodePane = ({ block }) => {
  const [index, setIndex] = React.useState(0);
  const view = VIEWS[index];
  const text = block && block[view.field];
  return (
    <Section
      title="Latest Program"
      aside={
        <ContentSwitcher
          size="sm"
          className="sd-switch"
          aria-label="Program view"
          selectedIndex={index}
          onChange={({ index: i }) => setIndex(i)}
        >
          {VIEWS.map((v) => (
            <Switch key={v.key} name={v.key} text={v.label} />
          ))}
        </ContentSwitcher>
      }
    >
      <p className="sd-code-note">{view.note}</p>
      {text ? (
        // the listing keeps its indentation (scrolls sideways); the prompt is one long line, so wrap it
        <CodeSnippet
          type="multi"
          className="sd-code"
          wrapText={view.key !== "readable"}
          feedback="Copied"
          maxCollapsedNumberOfRows={16}
          aria-label={`${view.label} program`}
        >
          {text}
        </CodeSnippet>
      ) : (
        <p className="sd-empty">{view.empty}</p>
      )}
    </Section>
  );
};
