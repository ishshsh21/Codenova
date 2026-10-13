import { useCallback, useEffect, useState } from 'react';
import type { GmailAccounts } from '../types';
import { getGmailAccounts } from '../api/client';

/** Fired whenever the selected Gmail account changes, so Gmail views can reload. */
export const ACCOUNT_CHANGED_EVENT = 'gmail-account-changed';

export function useGmailAccounts() {
  const [data, setData] = useState<GmailAccounts | null>(null);
  const refresh = useCallback(() => getGmailAccounts().then(setData).catch(() => undefined), []);
  useEffect(() => { refresh(); }, [refresh]);
  return { data, setData, refresh };
}

export function selectedAccountName(data: GmailAccounts | null): string | null {
  if (!data) return null;
  if (data.selected === 'all') return data.accounts.length > 1 ? 'All accounts' : null;
  const account = data.accounts.find((item) => item.id === data.selected);
  return account ? account.label || account.email : null;
}
