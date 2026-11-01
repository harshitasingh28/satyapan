import Link from "next/link";

export default function NotFound() {
  return (
    <div className="page py-16">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-3 measure text-muted">There is no page at this address. Check the link, or start from one of these.</p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href="/verify" className="btn btn-primary">
          Verify a message
        </Link>
        <Link href="/" className="btn btn-secondary">
          Go to the home page
        </Link>
      </div>
    </div>
  );
}
