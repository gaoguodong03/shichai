export type ModelParams = {
  temperature: string
  top_p: string
  max_tokens: string
  presence_penalty: string
  frequency_penalty: string
  seed: string
  /** Freeform JSON object string for model-specific params (extra_body). */
  extra_body: string
}
