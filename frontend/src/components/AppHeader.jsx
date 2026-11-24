// The top bar: the product name, whether production is being polled, and the
// board-wide actions (pause, trigger types, export, reset, theme).
import React from "react";
import {
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderName,
  HeaderPanel,
  Tag,
  Toggle,
} from "@carbon/react";
import { Asleep, Download, Light, Pause, Play, Reset, SettingsAdjust } from "@carbon/icons-react";
import { TRIGGERS } from "../constants";

export const AppHeader = ({
  pollingOn,
  onTogglePolling,
  triggerCfg,
  onToggleTrigger,
  onExport,
  onReset,
  theme,
  onToggleTheme,
}) => {
  const [panelOpen, setPanelOpen] = React.useState(false);
  return (
    <Header aria-label="Learner Modeling Dashboard" className="lmd-header">
      <HeaderName href="#" prefix="INVITE" onClick={(e) => e.preventDefault()}>
        Learner Modeling Dashboard
      </HeaderName>
      <Tag
        type={pollingOn ? "green" : "warm-gray"}
        size="sm"
        className="live-state"
        title={
          pollingOn
            ? "Fetching new activity from production"
            : "The daemon is making no requests to production"
        }
      >
        {pollingOn ? "Live" : "Polling paused"}
      </Tag>
      <HeaderGlobalBar>
        <HeaderGlobalAction
          aria-label={
            pollingOn
              ? "Pause polling: stop all requests to the production server. The board keeps the last data."
              : "Resume polling: fetch new events from production again."
          }
          tooltipAlignment="end"
          onClick={onTogglePolling}
        >
          {pollingOn ? <Pause size={20} /> : <Play size={20} />}
        </HeaderGlobalAction>
        <HeaderGlobalAction
          aria-label="Triggers: turn trigger types on or off"
          aria-expanded={panelOpen}
          isActive={panelOpen}
          tooltipAlignment="end"
          onClick={() => setPanelOpen((p) => !p)}
        >
          <SettingsAdjust size={20} />
        </HeaderGlobalAction>
        <HeaderGlobalAction
          aria-label="Export: download a zip of CSV snapshots of all data"
          tooltipAlignment="end"
          onClick={onExport}
        >
          <Download size={20} />
        </HeaderGlobalAction>
        <HeaderGlobalAction
          aria-label="Reset: clear this board's session data. A CSV backup is saved first."
          tooltipAlignment="end"
          onClick={onReset}
        >
          <Reset size={20} />
        </HeaderGlobalAction>
        <HeaderGlobalAction
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          tooltipAlignment="end"
          onClick={onToggleTheme}
        >
          {theme === "dark" ? <Light size={20} /> : <Asleep size={20} />}
        </HeaderGlobalAction>
      </HeaderGlobalBar>
      <HeaderPanel expanded={panelOpen} aria-label="Triggers" className="trigger-panel">
        <h2>Triggers</h2>
        {Object.entries(TRIGGERS).map(([type, { label }]) => (
          <Toggle
            key={type}
            id={`trigger-${type}`}
            size="sm"
            labelText={label}
            labelA="Off"
            labelB="On"
            toggled={triggerCfg[type] !== false}
            onToggle={() => onToggleTrigger(type)}
          />
        ))}
      </HeaderPanel>
    </Header>
  );
};
