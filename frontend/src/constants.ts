/** Shared constants used across components. */

export interface ProviderPreset {
  name: string;
  url: string;
  models?: string[]; // preset model IDs (optional, for setup wizard)
}

export const QUICK_PRESETS: ProviderPreset[] = [
  { name: 'DeepSeek', url: 'https://api.deepseek.com', models: ['deepseek-v4-flash', 'deepseek-chat'] },
  { name: '通义千问', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-plus', 'qwen-max'] },
  { name: 'GLM', url: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-4-plus', 'glm-4-flash'] },
  { name: 'Kimi', url: 'https://api.moonshot.cn/v1', models: ['moonshot-v1-8k'] },
  { name: 'Step', url: 'https://api.stepfun.com/v1' },
  { name: 'MiniMax', url: 'https://api.minimax.chat/v1' },
  { name: 'OpenAI', url: 'https://api.openai.com/v1' },
];

export const CLIENT_TYPE_OPTIONS = [
  { value: 'openai' as const, label: 'OpenAI 兼容' },
  { value: 'anthropic' as const, label: 'Anthropic' },
  { value: 'gemini' as const, label: 'Google Gemini' },
];
