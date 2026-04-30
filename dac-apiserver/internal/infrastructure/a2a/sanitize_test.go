package a2a

import "testing"

func TestStripSuccessMarker(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{
			name: "empty",
			in:   "",
			want: "",
		},
		{
			name: "no marker passthrough",
			in:   "hello world\n",
			want: "hello world\n",
		},
		{
			name: "marker on its own trailing line",
			in:   "answer body\nreason: The current answer addresses the question very well.\n",
			want: "answer body",
		},
		{
			name: "marker without trailing newline",
			in:   "answer body\nreason: The current answer addresses the question very well.",
			want: "answer body",
		},
		{
			name: "marker only",
			in:   "reason: The current answer addresses the question very well.\n",
			want: "",
		},
		{
			name: "marker between paragraphs preserves single blank line",
			in:   "first paragraph\n\nreason: The current answer addresses the question very well.\n\nsecond paragraph",
			want: "first paragraph\n\nsecond paragraph",
		},
		{
			name: "case insensitive",
			in:   "answer\nReason: The Current Answer Addresses The Question Very Well.\n",
			want: "answer",
		},
		{
			name: "marker with extra horizontal whitespace",
			in:   "answer\n  reason:  The current answer addresses the question very well.  \n",
			want: "answer",
		},
		{
			name: "unrelated reason line stays intact",
			in:   "reason: anything else\n",
			want: "reason: anything else\n",
		},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			got := stripSuccessMarker(tc.in)
			if got != tc.want {
				t.Fatalf("stripSuccessMarker mismatch\nin:   %q\nwant: %q\ngot:  %q", tc.in, tc.want, got)
			}
		})
	}
}
