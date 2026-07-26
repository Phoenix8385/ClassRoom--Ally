import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Classroom Ally - Live Session",
  description:
    "Real-time Indian Sign Language interpretation — live captions and a signing avatar for the classroom.",
};

// Lock zoom so the signing avatar and captions stay put on assistive/AAC devices
// that would otherwise pinch-zoom the live view. Server-Component export only —
// the page itself is a Client Component and cannot declare viewport/metadata.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function ClassroomLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
