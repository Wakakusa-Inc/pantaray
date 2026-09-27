// Flip this flag to restore Pantaray account login in desktop and web builds.
// ChatGPT login and API-key connections are independent of this account login.
// It also decides whether the Supabase, account portal and Cloud proxy settings are
// required: the build scripts load this file directly, so it must stay plain enough
// for Node's type stripping.
export const PANTARAY_ACCOUNT_LOGIN_ENABLED = false;
