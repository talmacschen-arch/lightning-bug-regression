import { useState } from 'react';
import { Button } from '@/components/ui/button';

type ActiveTab = 'A' | 'B';

export default function CaseNewPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('A');
  const [entryAText, setEntryAText] = useState('');
  const [entryBText, setEntryBText] = useState('');
  const [yamlText, setYamlText] = useState('');

  function handleEntryBChange(value: string) {
    setEntryBText(value);
    setYamlText(value);
  }

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-2xl font-semibold">新建测试用例</h1>

      {/* Tab row */}
      <div className="flex gap-2 border-b pb-2">
        <button
          type="button"
          data-testid="tab-entry-a"
          className={
            activeTab === 'A'
              ? 'px-3 py-1.5 text-sm font-medium border-b-2 border-primary'
              : 'px-3 py-1.5 text-sm font-medium text-muted-foreground'
          }
          onClick={() => setActiveTab('A')}
        >
          从描述生成
        </button>
        <button
          type="button"
          data-testid="tab-entry-b"
          className={
            activeTab === 'B'
              ? 'px-3 py-1.5 text-sm font-medium border-b-2 border-primary'
              : 'px-3 py-1.5 text-sm font-medium text-muted-foreground'
          }
          onClick={() => setActiveTab('B')}
        >
          粘贴 YAML
        </button>
      </div>

      {/* Tab A content */}
      {activeTab === 'A' && (
        <div className="space-y-2">
          <textarea
            data-testid="textarea-entry-a"
            className="w-full border rounded p-2 text-sm h-24 resize-y"
            placeholder="描述你的测试用例，例如：验证 SELECT 1 返回 1"
            value={entryAText}
            onChange={(e) => setEntryAText(e.target.value)}
          />
          <Button
            type="button"
            data-testid="btn-generate-stub"
            variant="outline"
            size="sm"
            disabled
          >
            生成 YAML 草稿
          </Button>
        </div>
      )}

      {/* Tab B content */}
      {activeTab === 'B' && (
        <textarea
          data-testid="textarea-entry-b"
          className="w-full border rounded p-2 text-sm h-24 resize-y"
          placeholder="粘贴 YAML 内容"
          value={entryBText}
          onChange={(e) => handleEntryBChange(e.target.value)}
        />
      )}

      {/* Main YAML editor */}
      <textarea
        data-testid="textarea-yaml-editor"
        className="w-full border rounded p-2 text-sm font-mono h-64 resize-y"
        placeholder="YAML 内容将显示在此处"
        value={yamlText}
        onChange={(e) => setYamlText(e.target.value)}
      />

      {/* Bottom row: buttons + step results panel */}
      <div className="flex gap-4">
        {/* Left: action buttons */}
        <div className="flex gap-2 items-start">
          <Button
            type="button"
            data-testid="btn-validate"
            variant="outline"
          >
            Validate
          </Button>
          <Button
            type="button"
            data-testid="btn-try"
            variant="outline"
            disabled
          >
            Try
          </Button>
          <Button
            type="button"
            data-testid="btn-save"
            disabled
          >
            Save
          </Button>
        </div>

        {/* Right: step results panel */}
        <div
          data-testid="panel-step-results"
          className="flex-1 border rounded p-2 min-h-[80px] overflow-y-auto text-sm text-muted-foreground"
        >
          {/* Step results will appear here after Try */}
        </div>
      </div>
    </div>
  );
}
