export type BoolChoice = '' | 'true' | 'false'

export type ModelParams = {
  temperature: string
  top_p: string
  max_tokens: string
  presence_penalty: string
  frequency_penalty: string
  seed: string
  enable_thinking: BoolChoice
  thinking_budget: string
  thinking: BoolChoice
  do_sample: BoolChoice
  top_k: string
  gemini_thinking_level: '' | 'low'
}
