interface EditorProps {
  value: string;
  onChange: (value: string) => void;
}

function Editor({ value, onChange }: EditorProps): JSX.Element {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="editor-pane"
      aria-label="Markdown editor"
      placeholder="Type your markdown here..."
    />
  );
}

export default Editor;
