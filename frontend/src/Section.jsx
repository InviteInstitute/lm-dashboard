// A titled block of the student sheet. `aside` sits at the right end of the
// heading row (a tab switch, a run picker, a count).
import React from "react";

export const Section = ({ title, aside, children }) => (
  <section className="sd-section">
    <div className="sd-section-head">
      <h3>{title}</h3>
      {aside}
    </div>
    {children}
  </section>
);
