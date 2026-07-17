import type { components } from "@novel-platform/api-client";

type Schemas = components["schemas"];

export type ApiErrorBody = Schemas["ErrorResponse"];
export type FileFormat = Schemas["FileFormat"];
export type Book = Schemas["BookResponse"];
export type BookListItem = Schemas["BookListItem"];
export type BookPreference = Schemas["BookPreferenceResponse"];
export type BookPatchPayload = Schemas["BookPatch"];
export type ContentRole = Schemas["EditionResponse"]["content_role"];
export type CreateBookPayload = Schemas["BookCreate"];
export type CreateEditionPayload = Schemas["EditionCreate"];
export type CreationMethod = Schemas["EditionResponse"]["creation_method"];
export type Device = Schemas["DeviceResponse"];
export type DevicePlatform = Schemas["DeviceResponse"]["platform"];
export type EditionFile = Schemas["EditionFileResponse"];
export type Edition = Schemas["EditionResponse"];
export type BookDetail = Schemas["BookDetailResponse"];
export type EditionStatus = Schemas["EditionResponse"]["status"];
export type CredentialLoginPayload = Schemas["CredentialLoginRequest"];
export type LoginDevice = Schemas["LoginDeviceResponse"];
export type LoginSession = Schemas["LoginSessionResponse"];
export type Me = Schemas["MeResponse"];
export type ImportOperation = Schemas["ImportOperation"];
export type ImportStatus = Schemas["ImportStatus"];
export type ImportRecord = Schemas["ImportResponse"];
type ImportCommitDefaults = "edition_status" | "set_preferred";
export type ImportCommitPayload =
  & Omit<Schemas["ImportCommitRequest"], ImportCommitDefaults>
  & Partial<Pick<Schemas["ImportCommitRequest"], ImportCommitDefaults>>;
export type ImportCommitResult = Schemas["ImportCommitResponse"];
export type PatchEditionPayload = Schemas["EditionPatch"];
export type PatchPreferencePayload = Schemas["BookPreferencePatch"];
export type ProfilePayload = Schemas["ProfilePatch"];
export type ReaderOpen = Schemas["ReaderOpenResponse"];
export type ReaderSection = Schemas["ReaderSectionResponse"];
export type ReaderSettings = Schemas["ReaderSettingsResponse"];
export type ReaderSettingsPayload = Schemas["ReaderSettingsPatch"];
export type ReadingProgress = Schemas["ReadingProgressResponse"];
export type ReadingProgressPayload = Schemas["ReadingProgressUpdate"];
export type RecentReading = Schemas["RecentReadingResponse"];
export type Session = Schemas["SessionResponse"];
export type Series = Schemas["SeriesResponse"];
export type SeriesDetail = Schemas["SeriesDetailResponse"];
export type SeriesCreatePayload = Schemas["SeriesCreate"];
export type SeriesPatchPayload = Schemas["SeriesPatch"];
export type TokenResponse = Schemas["TokenResponse"];
export type TranslationOrigin = NonNullable<
  Schemas["EditionResponse"]["translation_origin"]
>;
export type User = Schemas["UserResponse"];
export type UserRole = Schemas["UserResponse"]["role"];
export type UserStatus = Schemas["UserResponse"]["status"];
export type PublicSiteSettings = Schemas["PublicSiteSettingsResponse"];
export type SiteSettings = Schemas["SiteSettingsResponse"];
export type SiteSettingsPatch = Schemas["SiteSettingsPatch"];
export type ReaderIdentity = Schemas["ReaderResponse"];
export type ReaderCreatePayload = Schemas["ReaderCreate"];
export type ReaderPatchPayload = Schemas["ReaderPatch"];
export type CredentialReissuePayload = Schemas["CredentialReissueRequest"];
export type IssuedReaderCredential = Schemas["IssuedReaderCredentialResponse"];
export type Passkey = Schemas["PasskeyResponse"];
export type PasskeyRegistrationResult = Schemas["PasskeyRegistrationResponse"];
export type WebAuthnOptions = Schemas["WebAuthnOptionsResponse"];
export type SecurityAuditEvent = Schemas["SecurityAuditEventResponse"];
