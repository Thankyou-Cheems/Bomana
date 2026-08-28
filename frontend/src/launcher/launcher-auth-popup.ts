export const AUTHORIZATION_COMPLETE_MESSAGE = "cheemspay:device-authorization-complete";

export interface AuthorizationPopup {
  readonly closed: boolean;
  readonly location: { replace(url: string): void };
  close(): void;
}

export type AuthorizationMode = "popup" | "redirect";

type PopupOpener = (url?: string | URL, target?: string, features?: string) => AuthorizationPopup | null;

export interface AuthorizationAttempt<T> {
  readonly access: T;
  readonly popup: AuthorizationPopup | null;
  readonly blocked: boolean;
}

export function openAuthorizationPopup(open: PopupOpener): AuthorizationPopup | null {
  return open(
    "about:blank",
    "bomana-cheemspay-auth",
    "popup=yes,width=520,height=760,resizable=yes,scrollbars=yes",
  );
}

export async function beginAuthorizationAttempt<T extends {
  readonly state: string;
  readonly verificationURL?: string;
  readonly userCode?: string;
}>(
  begin: () => Promise<T>,
  open: PopupOpener,
  expectedOrigin: string,
): Promise<AuthorizationAttempt<T>> {
  const popup = openAuthorizationPopup(open);
  try {
    const access = await begin();
    let blocked = false;
    if (access.state === "pending" && access.verificationURL && access.userCode) {
      const destination = authorizationVerificationURL(access.verificationURL, expectedOrigin, "popup");
      if (popup && !popup.closed) popup.location.replace(destination.href);
      else blocked = true;
    }
    return Object.freeze({ access, popup, blocked });
  } catch (error) {
    popup?.close();
    throw error;
  }
}

export function authorizationVerificationURL(raw: string, expectedOrigin: string, mode: AuthorizationMode): URL {
  const url = new URL(raw);
  if (url.origin !== expectedOrigin || url.username || url.password || url.pathname !== "/device") {
    throw new Error("CheemsPay 授权地址不受信任");
  }
  url.searchParams.set("launcher", "bomana");
  if (mode === "redirect") url.searchParams.set("return_mode", "redirect");
  else url.searchParams.delete("return_mode");
  return url;
}

export function acceptsAuthorizationCompletion(
  event: { readonly origin: string; readonly source: unknown; readonly data: unknown },
  popup: unknown,
  expectedOrigin: string,
  expectedUserCode: string,
): boolean {
  if (event.origin !== expectedOrigin || event.source !== popup || !event.data || typeof event.data !== "object") return false;
  const message = event.data as Record<string, unknown>;
  return message.type === AUTHORIZATION_COMPLETE_MESSAGE
    && message.userCode === expectedUserCode.trim().toUpperCase();
}
