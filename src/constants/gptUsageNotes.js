const UPI_LINK_LINES_EN = [
  'Sign in to the site first (free tool).',
  'Paste a full Session JSON that includes accessToken and sessionToken.',
  'The ChatGPT account must be Free and eligible for the first-month free promo.',
  'Extraction usually takes 30–90 seconds; keep the page open until it finishes.',
  'Share the resulting UPI link with an India-region user (PhonePe / GPay / Paytm).',
];

/**
 * Usage copy for GPT portal tools.
 * Only the upiLink tool is bundled in this repository.
 */
export function gptToolUsageBundle(language = 'en', tool = 'upiLink') {
  if (tool !== 'upiLink') {
    return { title: 'Usage', lines: [] };
  }
  return {
    title: 'How to use',
    lines: [...UPI_LINK_LINES_EN],
  };
}

export default gptToolUsageBundle;
