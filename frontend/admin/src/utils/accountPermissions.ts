import type { AccountProfile } from "../api/auth";

function isFormal(account: AccountProfile): boolean {
  return (account.kind ?? account.account_type ?? "formal") === "formal";
}

export function isVendorUser(account: AccountProfile): boolean {
  return isFormal(account) && account.role === "user" && Boolean(account.vendor_name);
}

export function canManageVendorAccounts(account: AccountProfile | null): boolean {
  return account?.role === "root"
    || (account?.role === "admin" && account.account_management_access === true);
}

export function canOpenAccountKeys(account: AccountProfile | null): boolean {
  return Boolean(account && isFormal(account) && !isVendorUser(account));
}
