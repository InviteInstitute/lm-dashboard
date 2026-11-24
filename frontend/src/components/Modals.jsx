// The board's two confirmations: the research login that unlocks ZANY's logs,
// and resetting the board for a fresh session.
import { InlineNotification, Modal, PasswordInput, TextInput } from "@carbon/react";

// `unlock` is the form's state while it is open ({email, password, error, busy}),
// null while closed.
export const UnlockModal = ({ unlock, onChange, onSubmit, onClose }) => (
  <Modal
    open={!!unlock}
    modalLabel="ZANY's logs"
    modalHeading="Sign in with the research login"
    primaryButtonText={unlock?.busy ? "Checking..." : "Unlock"}
    primaryButtonDisabled={!unlock?.email || !unlock?.password || unlock?.busy}
    secondaryButtonText="Cancel"
    onRequestClose={onClose}
    onRequestSubmit={onSubmit}
  >
    <p className="unlock-intro">
      ZANY's logs are for the research team. Use the same login as ATLAS's research pages; ATLAS
      checks it. This browser stays unlocked for 12 hours.
    </p>
    <TextInput
      id="unlock-email"
      labelText="Email"
      type="email"
      autoComplete="username"
      value={unlock?.email || ""}
      onChange={(e) => onChange({ email: e.target.value })}
    />
    <PasswordInput
      id="unlock-password"
      labelText="Password"
      autoComplete="current-password"
      value={unlock?.password || ""}
      onChange={(e) => onChange({ password: e.target.value })}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSubmit();
      }}
    />
    {unlock?.error && (
      <InlineNotification
        kind="error"
        lowContrast
        hideCloseButton
        title="Not unlocked"
        subtitle={unlock.error}
      />
    )}
  </Modal>
);

export const ResetModal = ({ open, onClose, onConfirm }) => (
  <Modal
    open={open}
    danger
    className="reset-modal"
    modalLabel="This board"
    modalHeading="Reset the board?"
    primaryButtonText="Reset"
    secondaryButtonText="Cancel"
    onRequestClose={onClose}
    onRequestSubmit={() => {
      onClose();
      onConfirm();
    }}
  >
    <p>
      Every student starts fresh on this board: runs, episodes, goal evidence, alerts, trigger
      history and switches from before now are hidden, and your notes, picks and pick history are
      cleared. A CSV backup, notes and picks included, is saved to exports/ first, so nothing is
      lost.
    </p>
    <p>
      Students stay tracked and present or absent is kept. Other boards are not affected, and
      production is untouched.
    </p>
  </Modal>
);
