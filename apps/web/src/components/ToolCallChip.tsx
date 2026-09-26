import type { Json } from '../types';

interface Props {
  tool: string;
  args: Record<string, Json>;
  decision: string;
  ok: boolean | null;
  output?: Json;
  error?: string | null;
}

export function ToolCallChip({ tool, args, decision, ok, output, error }: Props) {
  const state = decision !== 'ALLOW' ? 'blocked' : ok === false ? 'failed' : 'ok';
  return (
    <details className={`chip chip--${state}`}>
      <summary>
        <span className="chip__tool">{tool}</span>
        <span className="chip__decision">{decision}</span>
      </summary>
      <pre>{JSON.stringify({ args, output, error }, null, 2)}</pre>
    </details>
  );
}
