interface EditorProps {
  value: string;
  onChange: (value: string) => void;
}

export function Editor({ value, onChange }: EditorProps): JSX.Element {
  return (
    <div className="pane editor-pane">
      <div className="pane-header">Markdown</div>
      <textarea
        className="editor-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        aria-label="Markdown editor"
      />
    </div>
  );
}
