# Phase 2 mandatory content contract — empty to grow

Effective 2026-11-05, from the owner's explicit requirement. This contract takes precedence over earlier phase numbering, catalog population targets, seed plans, and content-related readiness gates. Phase 2 delivers reliable, extensible, owner-managed content infrastructure. Content population is an ongoing owner operation after deployment.

## Initial state and scope

The application starts with zero educational content records. No real books, chapters, lessons, exercises, or educational datasets are required for development, automated tests, acceptance, deployment, or activation of capabilities that do not depend on content. Do not fabricate, scrape, generate, or bulk-import educational content to fill the catalog. Synthetic fixtures are permitted exclusively in automated tests; application startup, migrations, development seeds, and runtime fallback planners must not insert or supply them.

A fully functional empty catalog is a successful Phase 2 outcome. Completion has no minimum book, chapter, lesson, subject, or curriculum count. A missing approved resource prevents only the operation requiring that resource, such as activation of a grounded study plan. Authentication, profile management, intake, health checks, and owner content management remain available.

## Incremental owner workflow

The authenticated owner/admin can create one book or resource, edit its metadata, save an incomplete draft, close the interface, and later resume editing the persisted entry. Subject, curriculum, edition, complete page counts, and a full table of contents are not prerequisites for registering a resource.

The owner can add chapters individually, then lessons, sections, topics, page ranges, and exercise ranges in any supported incremental order. Valid individual units can be reviewed, approved, and published independently of the completion or publication of the rest of the book. Further chapters can be added later without resetting, restructuring, or repopulating the catalog.

Lifecycle operations include save/edit draft, submit for review, approve, publish, reject, and archive. Editing previously approved or published metadata invalidates the previous approval and publication; the changed entry requires another explicit review. Archival preserves the record and its audit history and does not modify unrelated resources. Draft parent containers do not imply trusted publication of their metadata.

## Empty and partial catalog behavior

Services, APIs, owner interfaces, and agent integrations must handle an empty catalog, a single book with zero chapters, a single chapter, incomplete chapters, draft-only entries, approved/published entries, and resources in mixed completion states. Collection queries return valid empty lists; unavailable individual resources return a normal not-found response. Unknown counts remain unknown. No service invents missing structure, page/exercise counts, references, or citations.

An agent finding no usable trusted resources returns an explicit missing-content state. It does not substitute educational fixtures or ask the owner to fill a whole curriculum before unrelated work can continue.

## Trust, provenance, and rights

Only content explicitly approved by the authenticated owner and published may enter student-facing or trusted-agent workflows. Draft, pending review, rejected, archived, and merely approved-but-unpublished entries remain unavailable. AI suggestions, if supported, begin unverified and require the same review and approval.

Preserve provenance, source references, license identifiers, rights statements, ownership, review attribution, timestamps, and immutable audit history. Evaluate active usage rights independently of whether content exists or has been approved. Revoking rights removes the item from authorized reads and planning inputs. Publication does not itself grant usage rights. Archiving a container hides its dependent units without deleting or rewriting them.

## Required automated acceptance

Acceptance uses a fresh empty database and synthetic fixtures created only within tests. It must demonstrate all ten requirements:

1. Startup succeeds with zero educational records and inserts no content.
2. Catalog and owner collection APIs return valid empty responses; individual misses return valid not-found responses.
3. Agents handle missing resources without errors or fabricated references/citations.
4. The owner creates, saves, and retrieves a single book with no chapters.
5. The owner adds, reviews, approves, and publishes one chapter independently.
6. The owner adds further chapters later while preserving existing IDs and records.
7. Draft, unreviewed, and unpublished content is absent from student-facing and trusted-agent reads.
8. Approved and published content with active rights becomes available through authenticated catalog interfaces.
9. Archiving one unit/resource leaves unrelated records and their availability intact.
10. Phase 2 acceptance and completion do not depend on any real content or a population threshold.

The implementation and local verification evidence are recorded in `PHASE_2_EMPTY_TO_GROW_REPORT.md`. Historical phase reports remain historical evidence; they do not override this contract or assert acceptance of later changes.
