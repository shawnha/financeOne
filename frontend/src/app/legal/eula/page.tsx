import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "End-User License Agreement | FinanceOne",
  description: "FinanceOne End-User License Agreement",
}

export default function EulaPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 text-sm leading-7 text-zinc-800">
      <h1 className="text-2xl font-semibold">End-User License Agreement</h1>
      <p className="mt-1 text-zinc-500">Last Updated: April 28, 2026</p>

      <p className="mt-6">
        <strong>Application:</strong> FinanceOne (Hanah One Group Internal Accounting BPO)
        <br />
        <strong>Operator:</strong> Hanah One Inc. (&quot;Company&quot;)
      </p>

      <h2 className="mt-8 text-lg font-semibold">1. Acceptance of Terms</h2>
      <p>
        By accessing or using FinanceOne (the &quot;Application&quot;), you agree to be bound by this
        End-User License Agreement (&quot;EULA&quot;). FinanceOne is provided exclusively for internal
        accounting and bookkeeping operations of the Hanah One group of companies and authorized
        accounting partners. If you do not agree to these terms, do not use the Application.
      </p>

      <h2 className="mt-6 text-lg font-semibold">2. License Grant</h2>
      <p>
        The Company grants you a non-exclusive, non-transferable, revocable license to use the
        Application solely for authorized internal accounting, financial reporting, and BPO purposes
        within the Hanah One group of companies.
      </p>

      <h2 className="mt-6 text-lg font-semibold">3. Restrictions</h2>
      <p>You shall not:</p>
      <ul className="ml-6 list-disc space-y-1">
        <li>Distribute, sublicense, sell, rent, lease, or otherwise transfer the Application to third parties.</li>
        <li>Reverse-engineer, decompile, or disassemble the Application except as permitted by law.</li>
        <li>Use the Application to violate any law, regulation, or third-party right.</li>
        <li>Interfere with the operation of the Application or its underlying infrastructure.</li>
      </ul>

      <h2 className="mt-6 text-lg font-semibold">4. Data and Confidentiality</h2>
      <p>
        The Application processes financial, banking, payment, and tax data belonging to entities
        within the Hanah One group. You agree to maintain the confidentiality of all data, use it
        only for authorized accounting and reporting purposes, and not disclose data to unauthorized
        parties.
      </p>

      <h2 className="mt-6 text-lg font-semibold">5. Third-Party Integrations</h2>
      <p>
        The Application integrates with QuickBooks Online (Intuit), Mercury Bank, Codef, and other
        financial data providers. Use of these integrations is subject to the respective providers&apos;
        terms of service. The Company is not responsible for the availability, accuracy, or
        behavior of third-party services.
      </p>

      <h2 className="mt-6 text-lg font-semibold">6. Intellectual Property</h2>
      <p>
        All intellectual property rights in the Application, including software, design, logos, and
        documentation, remain the exclusive property of Hanah One Inc.
      </p>

      <h2 className="mt-6 text-lg font-semibold">7. Disclaimer of Warranties</h2>
      <p>
        The Application is provided &quot;AS IS&quot; without warranties of any kind, either express
        or implied, including but not limited to merchantability, fitness for a particular purpose,
        or non-infringement.
      </p>

      <h2 className="mt-6 text-lg font-semibold">8. Limitation of Liability</h2>
      <p>
        To the fullest extent permitted by law, the Company shall not be liable for any indirect,
        incidental, consequential, or punitive damages arising from the use of, or inability to
        use, the Application.
      </p>

      <h2 className="mt-6 text-lg font-semibold">9. Termination</h2>
      <p>
        The Company may terminate this EULA and your access to the Application at any time, with or
        without cause. Upon termination, you must cease all use of the Application and destroy any
        copies in your possession.
      </p>

      <h2 className="mt-6 text-lg font-semibold">10. Governing Law</h2>
      <p>
        This EULA is governed by the laws of the State of California, United States, without regard
        to conflict-of-laws principles. Any disputes shall be resolved in the courts located in Los
        Angeles County, California.
      </p>

      <h2 className="mt-6 text-lg font-semibold">11. Contact</h2>
      <p>
        Hanah One Inc.
        <br />
        Email: shawn@hanah1.com
      </p>
    </main>
  )
}
