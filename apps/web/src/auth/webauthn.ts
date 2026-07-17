function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = window.atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface DescriptorJson extends Omit<PublicKeyCredentialDescriptor, "id"> {
  id: string;
}

interface CreationOptionsJson extends Omit<PublicKeyCredentialCreationOptions, "challenge" | "user" | "excludeCredentials"> {
  challenge: string;
  user: Omit<PublicKeyCredentialUserEntity, "id"> & { id: string };
  excludeCredentials?: DescriptorJson[];
}

interface RequestOptionsJson extends Omit<PublicKeyCredentialRequestOptions, "challenge" | "allowCredentials"> {
  challenge: string;
  allowCredentials?: DescriptorJson[];
}

function descriptor(value: DescriptorJson): PublicKeyCredentialDescriptor {
  return { ...value, id: decodeBase64Url(value.id) };
}

export async function createPasskey(
  options: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (!window.PublicKeyCredential || !navigator.credentials) {
    throw new Error("当前浏览器不支持 Passkey/WebAuthn。");
  }
  const source = options as unknown as CreationOptionsJson;
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...source,
    challenge: decodeBase64Url(source.challenge),
    user: { ...source.user, id: decodeBase64Url(source.user.id) },
    excludeCredentials: source.excludeCredentials?.map(descriptor),
  };
  const created = await navigator.credentials.create({ publicKey });
  if (!(created instanceof PublicKeyCredential)) {
    throw new Error("安全设备未返回可用的 Passkey 凭证。");
  }
  const response = created.response as AuthenticatorAttestationResponse;
  return {
    id: created.id,
    rawId: encodeBase64Url(created.rawId),
    type: created.type,
    authenticatorAttachment: created.authenticatorAttachment,
    clientExtensionResults: created.getClientExtensionResults(),
    response: {
      attestationObject: encodeBase64Url(response.attestationObject),
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      transports: response.getTransports?.() ?? [],
    },
  };
}

export async function getPasskeyAssertion(
  options: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (!window.PublicKeyCredential || !navigator.credentials) {
    throw new Error("当前浏览器不支持 Passkey/WebAuthn。");
  }
  const source = options as unknown as RequestOptionsJson;
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...source,
    challenge: decodeBase64Url(source.challenge),
    allowCredentials: source.allowCredentials?.map(descriptor),
  };
  const assertion = await navigator.credentials.get({ publicKey });
  if (!(assertion instanceof PublicKeyCredential)) {
    throw new Error("安全设备未返回可用的登录凭证。");
  }
  const response = assertion.response as AuthenticatorAssertionResponse;
  return {
    id: assertion.id,
    rawId: encodeBase64Url(assertion.rawId),
    type: assertion.type,
    authenticatorAttachment: assertion.authenticatorAttachment,
    clientExtensionResults: assertion.getClientExtensionResults(),
    response: {
      authenticatorData: encodeBase64Url(response.authenticatorData),
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      signature: encodeBase64Url(response.signature),
      userHandle: response.userHandle ? encodeBase64Url(response.userHandle) : null,
    },
  };
}
