-- A stored provider turn is readable by exactly one provider account: an OpenAI
-- `encrypted_content` decrypts only for the organization that issued it, an
-- Anthropic thinking signature verifies only for the account that signed it,
-- and handing one back to another account is a 400 on a turn already paid for.
--
-- A run cannot change account while it lasts (the stop barrier cancels the
-- Action instead), but a follow-up or a restart resumes the same Action on
-- whatever connection is configured then and reads these rows back. So the
-- account is stored beside the turn, as `route_identity.ConnectionIdentity`
-- rendered into one comparable string: kind, provider, model, and an API key's
-- SHA-256 fingerprint or a ChatGPT account id. It holds no secret.
ALTER TABLE agent_action_steps ADD COLUMN provider_turn_identity TEXT CHECK (
    (provider_turn_identity IS NULL) = (provider_turn IS NULL)
    AND (
        provider_turn_identity IS NULL
        OR LENGTH(TRIM(provider_turn_identity)) > 0
    )
);
